import SwiftUI

@main
struct GalerieAufraeumerApp: App {
    @StateObject private var model = LibraryModel()
    @Environment(\.scenePhase) private var scenePhase

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
