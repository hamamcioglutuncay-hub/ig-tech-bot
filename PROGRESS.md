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
- İlk sürüm: 20 kaynak
- Türkçe oyun: Oyungezer, Merlin'in Kazanı, TurkMMO
- Kullanıcı isteği ama RSS'i yok: Multiplayer (akış boş/2024), Disket Kutusu (alan adı yanıt vermiyor), LEVEL (bmag.com.tr mağazasına yönleniyor)
- Oyungezer tarihleri saat dilimsiz → `tz: Europe/Istanbul` desteği eklendi
- Bağlantı kopmalarına 1 kez yeniden deneme
- Tekilleştirme: URL normalize + seen.json (30 gün) + benzer başlık birleştirme (aynı dil). Farklı dillerde aynı olay (ör. Wolfenstein 3 haberi 4 kaynakta) Faz 2'de Gemini ile birleştirilecek.
- Kaynak kategorisi kaynağa göre; teknoloji sitelerindeki oyun haberleri (ör. Webtekno'da GTA 6) Faz 2'de Gemini ile yeniden sınıflanacak.
- **Kaynak genişletme (kullanıcı isteği):** 55 kaynak — 17 EN teknoloji, 7 EN yapay zekâ (`topic: ai`), 8 TR teknoloji, 21 EN oyun, 5 TR oyun (+ ShiftDelete Oyun, Kayıp Rıhtım).
  Ayrı Türkçe YZ akışı bulunamadı. Denenip çalışmayanlar `feeds.yaml` sonunda listeli.
- Aynı link birden fazla akışta → `oyun` kategorisi ve `ai` etiketi korunur.
- Performans: başlık karşılaştırması 93 sn → <1 sn (kelime ön elemesi + önbellek). `collect` toplam ~13 sn.
- 15 test geçti. `python -m bot collect` ~835 tekil haber gösteriyor.

## Sıradaki adım
Faz 2 (anahtarlar ve metin üretimi) planını sunmak.

## Açık sorunlar
- gh token'ında `workflow` izni yok → Faz 5'ten önce kullanıcı `gh auth refresh -h github.com -s workflow` çalıştırmalı (workflow dosyalarını push etmek için gerekli).
