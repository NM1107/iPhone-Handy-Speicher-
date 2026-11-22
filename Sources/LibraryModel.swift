import Foundation
import Photos
import UIKit

/// Welche Medien angezeigt werden.
enum MediaFilter: String, CaseIterable, Identifiable {
    case alle = "Alles"
    case fotos = "Nur Fotos"
    case videos = "Nur Videos"
    case screenshots = "Nur Screenshots"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .alle: return "photo.on.rectangle"
        case .fotos: return "photo"
        case .videos: return "video"
        case .screenshots: return "camera.viewfinder"
        }
    }
}

/// Verwaltet die Galerie: was noch angeschaut werden muss, was behalten
/// und was zum Löschen markiert wurde.
@MainActor
final class LibraryModel: ObservableObject {
    @Published private(set) var authStatus: PHAuthorizationStatus
    /// Noch nicht angeschaute Medien – das erste Element wird angezeigt.
    @Published private(set) var queue: [PHAsset] = []
    /// Anzahl aller Medien im aktuellen Filter.
    @Published private(set) var totalInFilter = 0
    /// Zum Löschen markierte Medien (werden gesammelt gelöscht).
    @Published private(set) var marked: [PHAsset] = []
    @Published private(set) var markedBytes: Int64 = 0
    @Published private(set) var freedBytesTotal: Int64 = 0
    @Published private(set) var isLoading = false
    @Published private(set) var isDeleting = false
    @Published private(set) var canUndo = false
    @Published var message: String?

    @Published var filter: MediaFilter {
        didSet {
            guard filter != oldValue else { return }
            defaults.set(filter.rawValue, forKey: Keys.filter)
            reload()
        }
    }

    @Published var oldestFirst: Bool {
        didSet {
            guard oldestFirst != oldValue else { return }
            defaults.set(oldestFirst, forKey: Keys.oldestFirst)
            reload()
        }
    }

    /// true: nach links wischen = Behalten, nach rechts = Löschen.
    @Published var swipeLeftKeeps: Bool {
        didSet { defaults.set(swipeLeftKeeps, forKey: Keys.swipeLeftKeeps) }
    }

    private enum Keys {
        static let swipeLeftKeeps = "swipeLeftKeeps"
        static let kept = "keptIDs"
        static let marked = "markedIDs"
        static let filter = "filter"
        static let oldestFirst = "oldestFirst"
        static let freed = "freedBytesTotal"
    }

    private struct Decision {
        let asset: PHAsset
        let deleted: Bool
    }

    private let defaults = UserDefaults.standard
    private var keptIDs: Set<String>
    private var history: [Decision] = []
    private var sizeCache: [String: Int64] = [:]
    private var loadToken = 0
    private var saveTask: Task<Void, Never>?

    var hasAccess: Bool {
        authStatus == .authorized || authStatus == .limited
    }

    var current: PHAsset? { queue.first }

    var reviewedCount: Int { max(0, totalInFilter - queue.count) }

    var progress: Double {
        totalInFilter == 0 ? 0 : Double(reviewedCount) / Double(totalInFilter)
    }

    init() {
        authStatus = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        keptIDs = Set(UserDefaults.standard.stringArray(forKey: Keys.kept) ?? [])
        filter = MediaFilter(rawValue: UserDefaults.standard.string(forKey: Keys.filter) ?? "") ?? .alle
        oldestFirst = UserDefaults.standard.object(forKey: Keys.oldestFirst) as? Bool ?? false
        swipeLeftKeeps = UserDefaults.standard.object(forKey: Keys.swipeLeftKeeps) as? Bool ?? true
        freedBytesTotal = (UserDefaults.standard.object(forKey: Keys.freed) as? NSNumber)?.int64Value ?? 0
        if hasAccess {
            restoreMarked()
            reload()
        }
    }

    // MARK: - Zugriff

    func requestAccess() async {
        let status = await PHPhotoLibrary.requestAuthorization(for: .readWrite)
        authStatus = status
        if hasAccess {
            restoreMarked()
            reload()
        }
    }

    // MARK: - Laden

    func reload() {
        guard hasAccess else { return }
        isLoading = true
        loadToken += 1
        let token = loadToken
        let filter = self.filter
        let oldestFirst = self.oldestFirst
        let excluded = keptIDs.union(marked.map { $0.localIdentifier })
        history.removeAll()
        canUndo = false

        Task.detached(priority: .userInitiated) {
            let result = LibraryModel.fetch(filter, oldestFirst: oldestFirst)
            var remaining: [PHAsset] = []
            remaining.reserveCapacity(result.count)
            result.enumerateObjects { asset, _, _ in
                if !excluded.contains(asset.localIdentifier) {
                    remaining.append(asset)
                }
            }
            let finalList = remaining
            let total = result.count
            await MainActor.run {
                guard token == self.loadToken else { return }
                self.queue = finalList
                self.totalInFilter = total
                self.isLoading = false
            }
        }
    }

    nonisolated static func fetch(_ filter: MediaFilter, oldestFirst: Bool) -> PHFetchResult<PHAsset> {
        let options = PHFetchOptions()
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: oldestFirst)]
        switch filter {
        case .alle:
            options.predicate = NSPredicate(
                format: "mediaType == %@ OR mediaType == %@",
                NSNumber(value: PHAssetMediaType.image.rawValue),
                NSNumber(value: PHAssetMediaType.video.rawValue)
            )
            return PHAsset.fetchAssets(with: options)
        case .fotos:
            return PHAsset.fetchAssets(with: .image, options: options)
        case .videos:
            return PHAsset.fetchAssets(with: .video, options: options)
        case .screenshots:
            let albums = PHAssetCollection.fetchAssetCollections(
                with: .smartAlbum, subtype: .smartAlbumScreenshots, options: nil)
            if let album = albums.firstObject {
                return PHAsset.fetchAssets(in: album, options: options)
            }
            return PHAsset.fetchAssets(withLocalIdentifiers: [], options: nil)
        }
    }

    private func restoreMarked() {
        let ids = defaults.stringArray(forKey: Keys.marked) ?? []
        guard !ids.isEmpty else {
            marked = []
            markedBytes = 0
            return
        }
        let result = PHAsset.fetchAssets(withLocalIdentifiers: ids, options: nil)
        var list: [PHAsset] = []
        result.enumerateObjects { asset, _, _ in list.append(asset) }
        marked = list
        markedBytes = list.reduce(0) { $0 + size(of: $1) }
        scheduleSave()
    }

    // MARK: - Entscheidungen

    func keep() {
        guard let asset = queue.first else { return }
        queue.removeFirst()
        keptIDs.insert(asset.localIdentifier)
        record(Decision(asset: asset, deleted: false))
    }

    func markForDeletion() {
        guard let asset = queue.first else { return }
        queue.removeFirst()
        marked.append(asset)
        markedBytes += size(of: asset)
        record(Decision(asset: asset, deleted: true))
    }

    func undo() {
        guard let last = history.popLast() else { return }
        let id = last.asset.localIdentifier
        if last.deleted {
            if let index = marked.firstIndex(where: { $0.localIdentifier == id }) {
                marked.remove(at: index)
                markedBytes = max(0, markedBytes - size(of: last.asset))
            }
        } else {
            keptIDs.remove(id)
        }
        queue.insert(last.asset, at: 0)
        canUndo = !history.isEmpty
        scheduleSave()
    }

    /// Markiertes Element wieder herausnehmen (z. B. aus der Lösch-Liste).
    func unmark(_ asset: PHAsset) {
        let id = asset.localIdentifier
        guard let index = marked.firstIndex(where: { $0.localIdentifier == id }) else { return }
        marked.remove(at: index)
        markedBytes = max(0, markedBytes - size(of: asset))
        history.removeAll { $0.asset.localIdentifier == id }
        canUndo = !history.isEmpty
        queue.insert(asset, at: 0)
        scheduleSave()
    }

    private func record(_ decision: Decision) {
        history.append(decision)
        if history.count > 100 { history.removeFirst(history.count - 100) }
        canUndo = true
        scheduleSave()
    }

    // MARK: - Löschen

    func deleteMarked() async {
        guard !marked.isEmpty, !isDeleting else { return }
        isDeleting = true
        let toDelete = marked
        let bytes = markedBytes
        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.deleteAssets(toDelete as NSArray)
            }
            let ids = Set(toDelete.map { $0.localIdentifier })
            marked.removeAll { ids.contains($0.localIdentifier) }
            markedBytes = marked.reduce(0) { $0 + size(of: $1) }
            history.removeAll()
            canUndo = false
            freedBytesTotal += bytes
            saveNow()
            message = "\(toDelete.count) \(toDelete.count == 1 ? "Element" : "Elemente") gelöscht (\(Self.format(bytes))).\n\nWichtig: Wirklich frei wird der Speicher erst, wenn du in Fotos → Alben → „Zuletzt gelöscht“ leerst."
        } catch {
            if !Self.isUserCancel(error) {
                message = "Löschen hat nicht geklappt: \(error.localizedDescription)"
            }
        }
        isDeleting = false
    }

    private static func isUserCancel(_ error: Error) -> Bool {
        if let photosError = error as? PHPhotosError, photosError.code == .userCancelled {
            return true
        }
        let ns = error as NSError
        return ns.domain == NSCocoaErrorDomain && ns.code == 3072
    }

    // MARK: - Fortschritt

    func resetProgress() {
        keptIDs.removeAll()
        saveNow()
        reload()
    }

    func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 800_000_000)
            guard !Task.isCancelled else { return }
            self?.saveNow()
        }
    }

    func saveNow() {
        saveTask?.cancel()
        saveTask = nil
        defaults.set(Array(keptIDs), forKey: Keys.kept)
        defaults.set(marked.map { $0.localIdentifier }, forKey: Keys.marked)
        defaults.set(NSNumber(value: freedBytesTotal), forKey: Keys.freed)
    }

    // MARK: - Größe

    func size(of asset: PHAsset) -> Int64 {
        if let cached = sizeCache[asset.localIdentifier] { return cached }
        var total: Int64 = 0
        let selector = NSSelectorFromString("fileSize")
        for resource in PHAssetResource.assetResources(for: asset) where resource.responds(to: selector) {
            if let number = resource.value(forKey: "fileSize") as? NSNumber {
                total += number.int64Value
            }
        }
        sizeCache[asset.localIdentifier] = total
        return total
    }

    static func format(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}
