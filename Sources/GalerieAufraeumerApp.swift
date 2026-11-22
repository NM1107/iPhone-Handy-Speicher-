import AVFoundation
import SwiftUI

@main
struct GalerieAufraeumerApp: App {
    @StateObject private var model = LibraryModel()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // Videos mit Ton abspielen, auch wenn der Stummschalter an ist.
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { phase in
            if phase != .active {
                model.saveNow()
            }
        }
    }
}
