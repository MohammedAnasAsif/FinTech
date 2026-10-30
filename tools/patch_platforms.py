"""Run after `flutter create` in CI: app name, network permission, Windows exe name.

The platform folders (android/, windows/) are generated fresh on every build, so the
only hand-made platform settings live here."""
import pathlib
import re
import sys

app = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "app")

manifest = app / "android/app/src/main/AndroidManifest.xml"
if manifest.exists():
    m = manifest.read_text(encoding="utf-8")
    if "android.permission.INTERNET" not in m:
        m = m.replace("<application", '<uses-permission android:name="android.permission.INTERNET"/>\n    <application', 1)
    # the engine runs on your own PC over plain http on the local network
    if "usesCleartextTraffic" not in m:
        m = m.replace("<application", '<application\n        android:usesCleartextTraffic="true"', 1)
    m = re.sub(r'android:label="[^"]*"', 'android:label="TradeBot"', m, count=1)
    manifest.write_text(m, encoding="utf-8")
    print("patched", manifest)

cmake = app / "windows/CMakeLists.txt"
if cmake.exists():
    c = cmake.read_text(encoding="utf-8")
    c = re.sub(r'set\(BINARY_NAME "[^"]*"\)', 'set(BINARY_NAME "TradeBot")', c)
    cmake.write_text(c, encoding="utf-8")
    print("patched", cmake)

main_cpp = app / "windows/runner/main.cpp"
if main_cpp.exists():
    s = main_cpp.read_text(encoding="utf-8")
    s = re.sub(r'window\.Create\(L"[^"]*"', 'window.Create(L"TradeBot"', s)
    main_cpp.write_text(s, encoding="utf-8")
    print("patched", main_cpp)
