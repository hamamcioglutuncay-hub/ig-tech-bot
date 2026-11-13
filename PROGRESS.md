# PROGRESS.md — ilerleme durumu

Son güncelleme: 2026-11-13

## Fazlar
| Faz | Konu | Durum |
|---|---|---|
| 0 | Ortam ve repo | ✅ Tamamlandı (2026-11-13) |
| 1 | Haber toplama | ✅ Tamamlandı (2026-11-13) |
| 2 | Anahtarlar ve metin üretimi | ⏳ Sıradaki — plan onayı bekleniyor |
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

## Faz 1 sonuçları
- `feeds.yaml`: 20 çalışan kaynak (10 teknoloji: 5 EN + 5 TR; 10 oyun: 7 EN + 3 TR)
- Türkçe oyun: Oyungezer, Merlin'in Kazanı, TurkMMO
- Kullanıcı isteği ama RSS'i yok: Multiplayer (akış boş/2024), Disket Kutusu (alan adı yanıt vermiyor), LEVEL (bmag.com.tr mağazasına yönleniyor)
- Oyungezer tarihleri saat dilimsiz → `tz: Europe/Istanbul` desteği eklendi
- Bağlantı kopmalarına 1 kez yeniden deneme
- Tekilleştirme: URL normalize + seen.json (30 gün) + benzer başlık birleştirme (aynı dil). Farklı dillerde aynı olay (ör. Wolfenstein 3 haberi 4 kaynakta) Faz 2'de Gemini ile birleştirilecek.
- Kaynak kategorisi kaynağa göre; teknoloji sitelerindeki oyun haberleri (ör. Webtekno'da GTA 6) Faz 2'de Gemini ile yeniden sınıflanacak.
- 14 test geçti. `python -m bot collect` ~390 tekil haber gösteriyor.

## Sıradaki adım
Faz 2 (anahtarlar ve metin üretimi) planını sunmak.

## Açık sorunlar
- gh token'ında `workflow` izni yok → Faz 5'ten önce kullanıcı `gh auth refresh -h github.com -s workflow` çalıştırmalı (workflow dosyalarını push etmek için gerekli).
