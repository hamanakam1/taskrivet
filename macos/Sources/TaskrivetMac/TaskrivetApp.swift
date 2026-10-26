import SwiftUI

/// Taskrivet's native macOS window: the ticket loop, ledger tasks, and
/// session terminals, plus interactive PTY tabs. All ledger reads go through
/// the taskrivet CLI (argv, never a shell); all writes stay operator-driven
/// inside the terminal tabs themselves.
@main
struct TaskrivetApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup("Taskrivet") {
            if let error = state.bridgeError, state.bridge == nil {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.largeTitle)
                        .foregroundStyle(.orange)
                    Text("Cannot reach the taskrivet CLI")
                        .font(.headline)
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 460)
                    Button("Try again") {
                        state.connect()
                        state.refresh()
                    }
                }
                .padding(40)
                .frame(minWidth: 560, minHeight: 320)
            } else {
                MainView(state: state)
                    .frame(minWidth: 980, minHeight: 560)
            }
        }
        .defaultSize(width: 1280, height: 780)
    }
}
