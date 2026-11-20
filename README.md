# MLPS Lab

Die Website liegt vollständig im Ordner `docs/`. Die HTML-Dateien lassen sich direkt bearbeiten. Das gemeinsame Stylesheet für Anpassungen ist `docs/assets/site.css`, das JavaScript steht in `docs/assets/site.js`. Unter `assets/theme/` liegen die übernommenen Originalstile.

## Lokal ansehen

Im entpackten Projektordner ausführen und anschließend http://localhost:8000 öffnen.

```sh
python3 -m http.server 8000 --directory docs
```

## Inhalte pflegen

Eine Person bearbeitet beispielsweise ihre Biografie in `docs/jonathan-ott/index.html`. Bei Kursen, News und Themen sind die Übersichten ebenfalls direkt bearbeitbare HTML-Dateien. Wird ein Beitrag auf mehreren Übersichten angezeigt, müssen diese bei redaktionellen Änderungen mitgepflegt werden. Bestehende Ordnernamen sind öffentliche Permalinks.

Für ein Paper eine Datei in `data/publications/` anlegen oder bearbeiten. Eine ähnliche TOML-Datei ist die einfachste Vorlage. Titel, vollständiges Datum, Autoren, Venue und Links eintragen. In `profiles` die beteiligten Personen mit ihrem Profilnamen eintragen, etwa `["alexander-mattick", "christopher-mutschler"]`. Das optionale Feld `bibtex` enthält das kopierbare Zitat. Das optionale Feld `highlight` steuert die Auswahl oben auf der Publikationsseite. Ein neuer Eintrag kann für den Titel auf sein Paper verweisen. Eine eigene neue HTML-Detailseite lässt sich bei Bedarf anlegen.

```sh
python3 scripts/publications.py
```

Der Generator braucht Python ab 3.11 und schreibt die markierten Abschnitte der Gesamtlisten und Profile samt Folgeseiten. Anschließend TOML und aktualisierte HTML-Dateien gemeinsam committen. Alle übrigen Seiten kommen ohne Build-Schritt aus.

## GitHub Pages

Den Inhalt dieses Ordners in das Lehrstuhl-Repository übernehmen. Unter **Settings → Pages** die Veröffentlichung aus einem Branch wählen, den gewünschten Branch und den Ordner **/docs** auswählen. Zuerst die GitHub-Adresse testen. Die Umstellung von `mlps-lab.de` kann anschließend unabhängig vom Projekt erfolgen. Die ZIP-Datei enthält weder Zugangsdaten noch den WordPress-Rohexport.

## Übernahme

Die statischen Seiten verwenden öffentliches Original-HTML und die öffentlichen Inhalte des WordPress-Exports. Die fünf passwortgeschützten Seiten und private Inhalte sind ausgeschlossen. Das ehemalige Kontaktformular benötigt für die aktive Einreichung einen Dienst. Die statische Fassung verweist auf die Bewerbungs- und Kontaktinformationen. Externe Lehrmaterialien und Forschungsdaten bleiben an ihren bisherigen Downloadadressen. Verbleibende Abhängigkeiten der statischen Seiten stehen in MIGRATION.md.

## Fehlende Medien ergänzen

`python3 scripts/fetch_media.py --check` zeigt den lokalen Bestand. `python3 scripts/fetch_media.py --missing-only` lädt die noch fehlenden Dateien vom bisherigen Server und passt Verweise an. Wer die Dateien direkt vom Webspace kopiert, kann danach `python3 scripts/fetch_media.py --relink-only` ausführen. Mit `python3 scripts/fetch_media.py` lassen sich auch fehlende Originalauflösungen ergänzen. Das sollte vor der Umstellung der Domain erfolgen.
