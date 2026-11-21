import AVKit
import Photos
import SwiftUI

/// Lädt Bild bzw. Video für ein einzelnes Element der Galerie.
final class AssetLoader: ObservableObject {
    @Published var image: UIImage?
    @Published var player: AVPlayer?
    @Published var failed = false
    @Published var isDownloading = false

    private let manager = PHImageManager.default()
    private var imageRequest: PHImageRequestID = PHInvalidImageRequestID
    private var videoRequest: PHImageRequestID = PHInvalidImageRequestID
    private var started = false
    private var stopped = false

    func start(asset: PHAsset, size: CGSize) {
        guard !started else { return }
        started = true
        stopped = false

        let isVideo = asset.mediaType == .video
        let scale = UIScreen.main.scale
        let base = (size.width > 1 && size.height > 1) ? size : UIScreen.main.bounds.size
        let target = CGSize(width: base.width * scale, height: base.height * scale)

        let imageOptions = PHImageRequestOptions()
        imageOptions.deliveryMode = .opportunistic
        imageOptions.resizeMode = .fast
        imageOptions.isNetworkAccessAllowed = true
        imageOptions.progressHandler = { [weak self] _, _, _, _ in
            DispatchQueue.main.async {
                guard let self, !self.stopped else { return }
                self.isDownloading = true
            }
        }

        imageRequest = manager.requestImage(
            for: asset, targetSize: target, contentMode: .aspectFit, options: imageOptions
        ) { [weak self] image, info in
            let cancelled = (info?[PHImageCancelledKey] as? Bool) ?? false
            let degraded = (info?[PHImageResultIsDegradedKey] as? Bool) ?? false
            DispatchQueue.main.async {
                guard let self, !self.stopped else { return }
                if let image {
                    self.image = image
                    if !degraded { self.isDownloading = false }
                } else if !cancelled && !degraded && !isVideo {
                    self.failed = true
                    self.isDownloading = false
                }
            }
        }

        guard isVideo else { return }

        let videoOptions = PHVideoRequestOptions()
        videoOptions.isNetworkAccessAllowed = true
        videoOptions.deliveryMode = .automatic
        videoOptions.progressHandler = { [weak self] _, _, _, _ in
            DispatchQueue.main.async {
                guard let self, !self.stopped else { return }
                self.isDownloading = true
            }
        }

        videoRequest = manager.requestPlayerItem(forVideo: asset, options: videoOptions) { [weak self] item, _ in
            DispatchQueue.main.async {
                guard let self, !self.stopped else { return }
                self.isDownloading = false
                guard let item else {
                    if self.image == nil { self.failed = true }
                    return
                }
                let player = AVPlayer(playerItem: item)
                self.player = player
                player.play()
            }
        }
    }

    func stop() {
        stopped = true
        if imageRequest != PHInvalidImageRequestID { manager.cancelImageRequest(imageRequest) }
        if videoRequest != PHInvalidImageRequestID { manager.cancelImageRequest(videoRequest) }
        imageRequest = PHInvalidImageRequestID
        videoRequest = PHInvalidImageRequestID
        player?.pause()
        player = nil
    }

    deinit {
        player?.pause()
    }
}

/// Zeigt ein Foto groß an oder spielt ein Video ab.
struct AssetView: View {
    let asset: PHAsset
    @StateObject private var loader = AssetLoader()

    var body: some View {
        GeometryReader { geo in
            ZStack {
                if let player = loader.player {
                    VideoPlayer(player: player)
                } else if let image = loader.image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(width: geo.size.width, height: geo.size.height)
                    if asset.mediaType == .video {
                        Image(systemName: "play.circle.fill")
                            .font(.system(size: 64))
                            .foregroundStyle(Color.white.opacity(0.85))
                            .shadow(radius: 8)
                    }
                }

                if loader.failed {
                    VStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.largeTitle)
                        Text("Konnte nicht geladen werden")
                            .font(.subheadline)
                    }
                    .foregroundStyle(.secondary)
                } else if loader.image == nil && loader.player == nil {
                    VStack(spacing: 10) {
                        ProgressView()
                            .tint(.white)
                        if loader.isDownloading {
                            Text("Lade aus iCloud …")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if loader.isDownloading && (loader.image != nil) {
                    VStack {
                        HStack {
                            Spacer()
                            Label("iCloud", systemImage: "icloud.and.arrow.down")
                                .font(.caption.bold())
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(.ultraThinMaterial, in: Capsule())
                                .padding(10)
                        }
                        Spacer()
                    }
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .onAppear { loader.start(asset: asset, size: geo.size) }
            .onDisappear { loader.stop() }
        }
    }
}
