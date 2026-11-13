# PROGRESS.md — ilerleme durumu

Son güncelleme: 2026-11-13

## Fazlar
| Faz | Konu | Durum |
|---|---|---|
| 0 | Ortam ve repo | ✅ Tamamlandı (2026-11-13) |
| 1 | Haber toplama | ⏳ Sıradaki — plan onayı bekleniyor |
| 2 | Anahtarlar ve metin üretimi | ⬜ |
| 3 | Görsel ve tasarım | ⬜ |
| 4 | Instagram bağlantısı | ⬜ |
| 5 | Otomasyon | ⬜ |
| 6 | Canlıya alma ve bakım | ⬜ |

## Faz 0 sonuçları
- Repo: https://github.com/hamamcioglutuncay-hub/ig-tech-bot (public, `main`)
- Python 3.12.16 (Homebrew) + proje içi `.venv`
- gh 2.104.0, hesap `hamamcioglutuncay-hub` (zaten girişliydi)
- Masaüstü iCloud senkronu kapalı → `.env` ve `.venv` proje içinde, `.gitignore`'da
- Pre-commit gizli bilgi taraması (`.githooks/pre-commit` → `scripts/secret_scan.sh`), sahte anahtarla test edildi: commit'i durduruyor
- Not: Intel Mac + macOS 26 için Homebrew hazır paket yok; paketler kaynak koddan derleniyor (yavaş)

## Sıradaki adım
Faz 1 (haber toplama) planını sunmak.

## Açık sorunlar
- gh token'ında `workflow` izni yok → Faz 5'ten önce kullanıcı `gh auth refresh -h github.com -s workflow` çalıştırmalı (workflow dosyalarını push etmek için gerekli).
