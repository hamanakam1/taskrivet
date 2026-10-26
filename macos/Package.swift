// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "TaskrivetMac",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "TaskrivetMac", targets: ["TaskrivetMac"])
    ],
    dependencies: [
        .package(url: "https://github.com/migueldeicaza/SwiftTerm", from: "1.99.1")
    ],
    targets: [
        .executableTarget(
            name: "TaskrivetMac",
            dependencies: [.product(name: "SwiftTerm", package: "SwiftTerm")],
            path: "Sources/TaskrivetMac"
        ),
        .testTarget(
            name: "TaskrivetMacTests",
            dependencies: ["TaskrivetMac"],
            path: "Tests/TaskrivetMacTests"
        )
    ]
)
