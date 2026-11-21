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
                } else if let asset = model.current {
                    AssetView(asset: asset)
                        .id(asset.localIdentifier)
                        .clipShape(RoundedRectangle(cornerRadius: 20))
                } else {
                    DoneView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if let asset = model.current, !model.isLoading {
                InfoLine(asset: asset)
            }

            DecisionButtons()
        }
        .padding(.horizontal, 12)
        .padding(.top, 4)
        .padding(.bottom, 8)
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

    var body: some View {
        let disabled = model.current == nil || model.isLoading
        HStack(spacing: 10) {
            BigButton(title: "Behalten", icon: "checkmark", color: .green) {
                haptic(.light)
                model.keep()
            }
            BigButton(title: "Löschen", icon: "trash.fill", color: .red) {
                haptic(.medium)
                model.markForDeletion()
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 22)
                .stroke(Color(red: 0.55, green: 0.08, blue: 0.12), lineWidth: 2)
        )
        .frame(height: 96)
        .disabled(disabled)
        .opacity(disabled ? 0.4 : 1)
    }
}

private struct BigButton: View {
    let title: String
    let icon: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                Text(title)
            }
            .font(.title3.bold())
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
