import AVFoundation
import Photos
import SwiftUI
import UIKit

/// Lädt Bild bzw. Video für ein einzelnes Element der Galerie.
final class AssetLoader: ObservableObject {
    @Published var image: UIImage?
    @Published var player: AVPlayer?
    @Published var failed = false
    @Published var isDownloading = false
    @Published var isPlaying = false
    @Published var progress: Double = 0

    /// Nur die oberste Karte spielt Videos ab.
    var isActive = false {
        didSet { applyPlayback() }
    }

    private var userPaused = false
    private let manager = PHImageManager.default()
    private var imageRequest: PHImageRequestID = PHInvalidImageRequestID
    private var videoRequest: PHImageRequestID = PHInvalidImageRequestID
    private var started = false
    private var stopped = false
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?

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
                    if !degraded && !isVideo { self.isDownloading = false }
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
                self.attach(AVPlayer(playerItem: item))
            }
        }
    }

    private func attach(_ player: AVPlayer) {
        player.actionAtItemEnd = .none
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.2, preferredTimescale: 600), queue: .main
        ) { [weak self, weak player] time in
            guard let self, let item = player?.currentItem else { return }
            let duration = item.duration.seconds
            if duration.isFinite && duration > 0 {
                self.progress = min(1, max(0, time.seconds / duration))
            }
        }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: player.currentItem, queue: .main
        ) { [weak self, weak player] _ in
            player?.seek(to: .zero)
            guard let self, self.isActive, !self.userPaused else { return }
            player?.play()
        }
        self.player = player
        applyPlayback()
    }

    func togglePlayPause() {
        guard player != nil else { return }
        userPaused.toggle()
        applyPlayback()
    }

    private func applyPlayback() {
        guard let player else {
            isPlaying = false
            return
        }
        if isActive && !userPaused && !stopped {
            player.play()
            isPlaying = true
        } else {
            player.pause()
            isPlaying = false
        }
    }

    func stop() {
        stopped = true
        if imageRequest != PHInvalidImageRequestID { manager.cancelImageRequest(imageRequest) }
        if videoRequest != PHInvalidImageRequestID { manager.cancelImageRequest(videoRequest) }
        imageRequest = PHInvalidImageRequestID
        videoRequest = PHInvalidImageRequestID
        cleanUpPlayer()
    }

    private func cleanUpPlayer() {
        if let timeObserver, let player { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = nil
        player?.pause()
        player = nil
        isPlaying = false
    }

    deinit {
        if let timeObserver, let player { player.removeTimeObserver(timeObserver) }
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        player?.pause()
    }
}

/// Reine Video-Fläche ohne eigene Bedienelemente, damit das Wischen
/// auch auf Videos funktioniert.
final class PlayerUIView: UIView {
    override class var layerClass: AnyClass { AVPlayerLayer.self }
    var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
}

struct PlayerLayerView: UIViewRepresentable {
    let player: AVPlayer

    func makeUIView(context: Context) -> PlayerUIView {
        let view = PlayerUIView()
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ view: PlayerUIView, context: Context) {
        if view.playerLayer.player !== player {
            view.playerLayer.player = player
        }
    }
}

/// Zeigt ein Foto groß an oder spielt ein Video ab.
struct AssetView: View {
    let asset: PHAsset
    let isActive: Bool
    @StateObject private var loader = AssetLoader()

    var body: some View {
        GeometryReader { geo in
            ZStack {
                if let image = loader.image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(width: geo.size.width, height: geo.size.height)
                }

                if let player = loader.player {
                    PlayerLayerView(player: player)
                        .frame(width: geo.size.width, height: geo.size.height)
                }

                if asset.mediaType == .video && loader.image != nil && !loader.isPlaying {
                    Image(systemName: "play.circle.fill")
                        .font(.system(size: 68))
                        .foregroundStyle(Color.white.opacity(0.9))
                        .shadow(radius: 8)
                        .allowsHitTesting(false)
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

                VStack {
                    if loader.isDownloading && loader.image != nil {
                        HStack {
                            Spacer()
                            Label("iCloud", systemImage: "icloud.and.arrow.down")
                                .font(.caption.bold())
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(.ultraThinMaterial, in: Capsule())
                                .padding(10)
                        }
                    }
                    Spacer()
                    if loader.player != nil {
                        GeometryReader { bar in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Color.white.opacity(0.25))
                                Capsule().fill(Color.white)
                                    .frame(width: bar.size.width * loader.progress)
                            }
                        }
                        .frame(height: 4)
                        .padding(.horizontal, 14)
                        .padding(.bottom, 12)
                    }
                }
                .allowsHitTesting(false)
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .contentShape(Rectangle())
            .onTapGesture {
                if asset.mediaType == .video { loader.togglePlayPause() }
            }
            .onAppear {
                loader.isActive = isActive
                loader.start(asset: asset, size: geo.size)
            }
            .onDisappear { loader.stop() }
            .onChange(of: isActive) { active in
                loader.isActive = active
            }
        }
    }
}
