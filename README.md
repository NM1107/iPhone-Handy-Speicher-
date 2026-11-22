# Galerie aufräumen 📸🗑️

iPhone-App: Jedes Foto und Video aus deiner Galerie wird einmal groß angezeigt.
Unten tippst du links auf **Behalten** und rechts auf **Löschen**.

## Was die App kann

- Fotos groß anzeigen, Videos direkt abspielen (auch aus iCloud)
- **Behalten** (links) / **Löschen** (rechts), dazu ein Knopf für **Rückgängig**
- **Wischen:** nach links = Behalten, nach rechts = Löschen (im Menü umdrehbar). Videos: antippen = Pause/Weiter
- Zum Löschen Markiertes wird gesammelt. Oben auf den roten Papierkorb tippen,
  dann fragt iOS **einmal** für alle zusammen
- Merkt sich, was du schon angeschaut hast, und macht beim nächsten Start dort weiter
- Filter im Menü (•••): Alles / Nur Fotos / Nur Videos / Nur Screenshots,
  dazu Neueste oder Älteste zuerst
- Zeigt die Größe jedes Elements und wie viel Speicher schon frei gemacht wurde

⚠️ Gelöschtes liegt danach noch 30 Tage in Fotos → Alben → **„Zuletzt gelöscht“**.
Erst wenn du das leerst, ist der Speicher wirklich frei.

## So kommt die App aufs iPhone (ohne Mac)

1. **Bauen:** Sobald der Code auf GitHub liegt, baut GitHub die App automatisch
   (Reiter *Actions*). Fertig ist sie unter *Releases*: `GalerieAufraeumer.ipa`.
2. **Auf dem PC:** [Sideloadly](https://sideloadly.io) installieren. Dazu iTunes und
   iCloud **von der Apple-Website** installieren, nicht aus dem Microsoft Store.
3. iPhone per Kabel anschließen und dem PC vertrauen.
4. Die `.ipa` in Sideloadly ziehen, deine Apple-ID eintragen und auf **Start** klicken.
5. Auf dem iPhone: Einstellungen → Datenschutz & Sicherheit → **Entwicklermodus** an
   (iPhone startet neu). Danach Einstellungen → Allgemein → VPN & Geräteverwaltung →
   deine Apple-ID → **Vertrauen**.
6. App öffnen und „Voller Zugriff“ auf Fotos erlauben.

Mit einer kostenlosen Apple-ID läuft die App **7 Tage**. Danach in Sideloadly einfach
nochmal auf Start klicken. Mit „Auto-Refresh“ macht Sideloadly das automatisch, wenn
PC und iPhone im selben WLAN sind.

## Technik

SwiftUI + PhotoKit, ab iOS 16. Das Projekt wird mit XcodeGen (`project.yml`) erzeugt,
der Build läuft über `.github/workflows/build.yml` auf einem macOS-Runner.
