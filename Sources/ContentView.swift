import Photos
import SwiftUI
import UIKit

struct ContentView: View {
    @EnvironmentObject private var model: LibraryModel

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if model.hasAccess {
                ReviewView()
            } else {
                AccessView()
            }
        }
        .alert(
            "Hinweis",
            isPresented: Binding(
                get: { model.message != nil },
                set: { if !$0 { model.message = nil } }
            )
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.message ?? "")
        }
    }
}

// MARK: - Zugriff auf die Fotos

private struct AccessView: View {
    @EnvironmentObject private var model: LibraryModel

    var body: some View {
        VStack(spacing: 22) {
            Spacer()
            Image(systemName: "photo.stack")
                .font(.system(size: 72))
                .foregroundStyle(.green)
            Text("Galerie aufräumen")
                .font(.largeTitle.bold())
            Text("Jedes Foto und Video wird einmal groß angezeigt. Du entscheidest: behalten oder löschen – und machst so Speicher frei.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal)

            if model.authStatus == .notDetermined {
                Button {
                    Task { await model.requestAccess() }
                } label: {
                    Text("Zugriff auf Fotos erlauben")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.green, in: RoundedRectangle(cornerRadius: 16))
                        .foregroundStyle(.black)
                }
                .padding(.horizontal, 32)
                Text("Wähle „Vollen Zugriff erlauben“, damit die ganze Galerie angezeigt wird.")
                    .font(.footnote)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 32)
            } else {
                Text("Der Zugriff auf deine Fotos ist ausgeschaltet. Erlaube ihn in den Einstellungen unter „Fotos“ → „Voller Zugriff“.")
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                Button {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                } label: {
                    Text("Einstellungen öffnen")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.green, in: RoundedRectangle(cornerRadius: 16))
                        .foregroundStyle(.black)
                }
                .padding(.horizontal, 32)
            }
            Spacer()
        }
    }
}

// MARK: - Hauptansicht

private struct ReviewView: View {
    @EnvironmentObject private var model: LibraryModel
    @State private var dragOffset: CGSize = .zero
    @State private var flying = false
    @State private var passedThreshold = false

    static let threshold: CGFloat = 110

    var body: some View {
        VStack(spacing: 10) {
            TopBar()

            // Großer Bereich für Bild / Video (grün im Entwurf)
            ZStack {
                RoundedRectangle(cornerRadius: 20)
                    .fill(Color(white: 0.07))
                if model.isLoading {
                    VStack(spacing: 12) {
                        ProgressView().tint(.white)
                        Text("Galerie wird geladen …")
                            .foregroundStyle(.secondary)
                    }
                } else if model.current != nil {
                    CardStack(dragOffset: $dragOffset, onDragEnded: dragEnded, onDragChanged: dragChanged)
                } else {
                    DoneView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if let asset = model.current, !model.isLoading {
                InfoLine(asset: asset)
            }

            DecisionButtons(isBusy: flying) { keep in
                decide(keep: keep)
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 4)
        .padding(.bottom, 8)
    }

    private func dragChanged(_ translation: CGSize) {
        guard !flying else { return }
        dragOffset = CGSize(width: translation.width, height: translation.height * 0.15)
        let passed = abs(translation.width) > Self.threshold
        if passed != passedThreshold {
            passedThreshold = passed
            if passed { haptic(.soft) }
        }
    }

    private func dragEnded(_ translation: CGSize, _ predicted: CGSize) {
        guard !flying else { return }
        passedThreshold = false
        let width = abs(translation.width) > Self.threshold ? translation.width
            : (abs(predicted.width) > 320 ? predicted.width : 0)
        if width == 0 {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.72)) {
                dragOffset = .zero
            }
            return
        }
        let draggedLeft = width < 0
        let keep = draggedLeft == model.swipeLeftKeeps
        decide(keep: keep)
    }

    /// Karte zur passenden Seite rausfliegen lassen, dann entscheiden.
    private func decide(keep: Bool) {
        guard !flying, model.current != nil, !model.isLoading else { return }
        flying = true
        haptic(keep ? .light : .medium)
        let toLeft = keep == model.swipeLeftKeeps
        let distance = UIScreen.main.bounds.width + 250
        withAnimation(.easeIn(duration: 0.2)) {
            dragOffset = CGSize(width: toLeft ? -distance : distance, height: dragOffset.height)
        }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 200_000_000)
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                dragOffset = .zero
                if keep {
                    model.keep()
                } else {
                    model.markForDeletion()
                }
            }
            flying = false
        }
    }
}

/// Oberste Karte zum Wischen, die nächste liegt dahinter und lädt schon vor.
private struct CardStack: View {
    @EnvironmentObject private var model: LibraryModel
    @Binding var dragOffset: CGSize
    let onDragEnded: (CGSize, CGSize) -> Void
    let onDragChanged: (CGSize) -> Void

    private struct Item: Identifiable {
        let asset: PHAsset
        let isTop: Bool
        var id: String { asset.localIdentifier }
    }

    private var items: [Item] {
        let upcoming = Array(model.queue.prefix(2))
        var list: [Item] = []
        if upcoming.count > 1 { list.append(Item(asset: upcoming[1], isTop: false)) }
        if let first = upcoming.first { list.append(Item(asset: first, isTop: true)) }
        return list
    }

    private var progress: CGFloat {
        min(1, abs(dragOffset.width) / ReviewView.threshold)
    }

    var body: some View {
        ZStack {
            ForEach(items) { item in
                card(item)
            }
        }
    }

    @ViewBuilder
    private func card(_ item: Item) -> some View {
        let shape = RoundedRectangle(cornerRadius: 20)
        AssetView(asset: item.asset, isActive: item.isTop)
            .background(shape.fill(Color(white: 0.07)))
            .clipShape(shape)
            .overlay {
                if item.isTop { SwipeStamp(offset: dragOffset, leftKeeps: model.swipeLeftKeeps) }
            }
            .scaleEffect(item.isTop ? 1 : 0.93 + 0.07 * progress)
            .opacity(item.isTop ? 1 : 0.6 + 0.4 * Double(progress))
            .rotationEffect(.degrees(item.isTop ? Double(dragOffset.width / 22) : 0), anchor: .bottom)
            .offset(item.isTop ? dragOffset : .zero)
            .allowsHitTesting(item.isTop)
            .gesture(
                DragGesture(minimumDistance: 12, coordinateSpace: .global)
                    .onChanged { value in onDragChanged(value.translation) }
                    .onEnded { value in onDragEnded(value.translation, value.predictedEndTranslation) },
                including: item.isTop ? .all : .subviews
            )
    }
}

/// Farbiger Stempel „BEHALTEN“ / „LÖSCHEN“ beim Wischen.
private struct SwipeStamp: View {
    let offset: CGSize
    let leftKeeps: Bool

    var body: some View {
        let amount = min(1, abs(offset.width) / ReviewView.threshold)
        let draggedLeft = offset.width < 0
        let keep = draggedLeft == leftKeeps
        let color: Color = keep ? .green : .red
        ZStack(alignment: draggedLeft ? .topTrailing : .topLeading) {
            RoundedRectangle(cornerRadius: 20)
                .fill(color.opacity(0.28 * Double(amount)))
            Text(keep ? "BEHALTEN" : "LÖSCHEN")
                .font(.system(size: 34, weight: .black))
                .foregroundStyle(color)
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(color, lineWidth: 4))
                .rotationEffect(.degrees(draggedLeft ? 14 : -14))
                .padding(28)
        }
        .opacity(offset.width == 0 ? 0 : Double(amount))
        .allowsHitTesting(false)
    }
}

private struct TopBar: View {
    @EnvironmentObject private var model: LibraryModel

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(model.queue.count.formatted()) übrig")
                    .font(.headline)
                    .monospacedDigit()
                ProgressView(value: model.progress)
                    .tint(.green)
                Text("\(model.reviewedCount.formatted()) von \(model.totalInFilter.formatted()) angeschaut")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            Button {
                haptic(.light)
                model.undo()
            } label: {
                Image(systemName: "arrow.uturn.backward.circle.fill")
                    .font(.system(size: 30))
            }
            .disabled(!model.canUndo)
            .tint(.white)
            .accessibilityLabel("Rückgängig")

            Button {
                Task { await model.deleteMarked() }
            } label: {
                HStack(spacing: 6) {
                    if model.isDeleting {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "trash.fill")
                    }
                    VStack(alignment: .leading, spacing: 0) {
                        Text("\(model.marked.count)")
                            .font(.subheadline.bold())
                            .monospacedDigit()
                        Text(LibraryModel.format(model.markedBytes))
                            .font(.caption2)
                            .monospacedDigit()
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(
                    model.marked.isEmpty ? Color(white: 0.18) : Color.red,
                    in: RoundedRectangle(cornerRadius: 12)
                )
                .foregroundStyle(.white)
            }
            .disabled(model.marked.isEmpty || model.isDeleting)
            .accessibilityLabel("Markierte jetzt löschen")

            Menu {
                Picker("Anzeigen", selection: $model.filter) {
                    ForEach(MediaFilter.allCases) { filter in
                        Label(filter.rawValue, systemImage: filter.icon).tag(filter)
                    }
                }
                Picker("Wischen", selection: $model.swipeLeftKeeps) {
                    Label("← Behalten · Löschen →", systemImage: "hand.draw").tag(true)
                    Label("← Löschen · Behalten →", systemImage: "hand.draw").tag(false)
                }
                Picker("Reihenfolge", selection: $model.oldestFirst) {
                    Label("Neueste zuerst", systemImage: "arrow.down").tag(false)
                    Label("Älteste zuerst", systemImage: "arrow.up").tag(true)
                }
                Section {
                    Label("Bisher frei gemacht: \(LibraryModel.format(model.freedBytesTotal))", systemImage: "externaldrive.badge.checkmark")
                    if model.authStatus == .limited {
                        Label("Nur ausgewählte Fotos freigegeben", systemImage: "exclamationmark.triangle")
                    }
                }
                Section {
                    Button(role: .destructive) {
                        model.resetProgress()
                    } label: {
                        Label("Behaltene wieder anzeigen", systemImage: "arrow.counterclockwise")
                    }
                }
            } label: {
                Image(systemName: "ellipsis.circle.fill")
                    .font(.system(size: 30))
                    .foregroundStyle(.white)
            }
        }
    }
}

private struct InfoLine: View {
    @EnvironmentObject private var model: LibraryModel
    let asset: PHAsset

    var body: some View {
        HStack(spacing: 10) {
            Label(asset.mediaType == .video ? "Video" : "Foto",
                  systemImage: asset.mediaType == .video ? "video.fill" : "photo.fill")
            if asset.mediaType == .video {
                Text(Self.duration(asset.duration))
            }
            if let date = asset.creationDate {
                Text(date.formatted(date: .abbreviated, time: .shortened))
            }
            Spacer()
            Text(LibraryModel.format(model.size(of: asset)))
                .bold()
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .monospacedDigit()
        .lineLimit(1)
        .padding(.horizontal, 4)
    }

    static func duration(_ seconds: TimeInterval) -> String {
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

// MARK: - Behalten / Löschen (roter Bereich im Entwurf)

private struct DecisionButtons: View {
    @EnvironmentObject private var model: LibraryModel
    let isBusy: Bool
    let decide: (Bool) -> Void

    var body: some View {
        let disabled = model.current == nil || model.isLoading
        HStack(spacing: 10) {
            if model.swipeLeftKeeps {
                keepButton
                deleteButton
            } else {
                deleteButton
                keepButton
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 22)
                .stroke(Color(red: 0.55, green: 0.08, blue: 0.12), lineWidth: 2)
        )
        .frame(height: 96)
        .disabled(disabled || isBusy)
        .opacity(disabled ? 0.4 : 1)
    }

    private var keepButton: some View {
        BigButton(title: "Behalten", icon: "checkmark", color: .green,
                  arrowLeft: model.swipeLeftKeeps) {
            decide(true)
        }
    }

    private var deleteButton: some View {
        BigButton(title: "Löschen", icon: "trash.fill", color: .red,
                  arrowLeft: !model.swipeLeftKeeps) {
            decide(false)
        }
    }
}

private struct BigButton: View {
    let title: String
    let icon: String
    let color: Color
    /// Pfeil zeigt die Wischrichtung für diesen Knopf.
    let arrowLeft: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 2) {
                HStack(spacing: 8) {
                    Image(systemName: icon)
                    Text(title)
                }
                .font(.title3.bold())
                Text(arrowLeft ? "← wischen" : "wischen →")
                    .font(.caption2)
                    .opacity(0.8)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .foregroundStyle(.white)
            .background(color.opacity(0.85), in: RoundedRectangle(cornerRadius: 14))
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(color, lineWidth: 2)
            )
        }
        .buttonStyle(PressStyle())
    }
}

private struct PressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}

// MARK: - Alles durch

private struct DoneView: View {
    @EnvironmentObject private var model: LibraryModel

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)
            Text(model.totalInFilter == 0 ? "Hier gibt es nichts" : "Alles durchgeschaut!")
                .font(.title2.bold())

            if !model.marked.isEmpty {
                Button {
                    Task { await model.deleteMarked() }
                } label: {
                    Label("\(model.marked.count) Elemente löschen (\(LibraryModel.format(model.markedBytes)))",
                          systemImage: "trash.fill")
                        .font(.headline)
                        .padding()
                        .frame(maxWidth: .infinity)
                        .background(Color.red, in: RoundedRectangle(cornerRadius: 14))
                        .foregroundStyle(.white)
                }
                .disabled(model.isDeleting)
                .padding(.horizontal, 24)
            }

            Text("Danach in der Fotos-App unter Alben → „Zuletzt gelöscht“ leeren, damit der Speicher wirklich frei wird.")
                .font(.footnote)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 24)

            if model.totalInFilter > 0 {
                Button("Behaltene nochmal anschauen") {
                    model.resetProgress()
                }
                .font(.footnote)
            }
        }
        .padding()
    }
}

@MainActor
private func haptic(_ style: UIImpactFeedbackGenerator.FeedbackStyle) {
    UIImpactFeedbackGenerator(style: style).impactOccurred()
}
