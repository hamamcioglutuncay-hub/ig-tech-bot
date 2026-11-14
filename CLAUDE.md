# CLAUDE.md — ig-tech-bot proje kuralları

Her oturumda önce bu dosyayı ve `PROGRESS.md`'yi oku. Ayrıntılı şartname: `CLAUDE_CODE_MASTER_PROMPT_ig_tech_bot_v2.md`.

## Amaç
Instagram'da (@singleplayer_tr) her gün "Günün Teknoloji & Oyun Haberleri" Türkçe carousel'ini (kapak + önemine göre 3–8 haber + kapanış; API sınırı 10 slayt) yalnızca **ücretsiz katmanlar** ve **resmi API'ler** ile üretip paylaşan bot. Metinlerde haber sayısı yazılmaz.

## Kullanıcı
- macOS, Türkçe konuşur, teknik olmayan kullanıcı gibi takip eder; görsel tasarımcıdır (tasarım kararlarına dahil et).
- İnteraktif komutları (`gh auth login`, `sudo`) kendisi ayrı Terminal'de çalıştırır → komutun başına her zaman
  `cd "/Users/tuncayhamamcioglu/Desktop/Claude Projeler/ig_tech_bot"` ekle.
- Kullanıcının yapması gerekenler **"🧑 SENİN ADIMIN"** başlığıyla numaralı liste; bitince "tamam" yazması istenir.

## Kesin kurallar
1. **Gizli bilgi:** Anahtar/token'ı sohbete yazdırma (yazılırsa uyar, yenilet). `.env`'yi kullanıcı kendisi doldurur (`open -e .env`).
   `.env` içeriği asla ekrana basılmaz, `cat`'lenmez, loglanmaz, commit edilmez. `python -m bot check` yalnızca maskeli sonuç (en fazla son 4 karakter).
   Secrets aktarımı: `gh secret set -f .env`. Her commit öncesi gizli değer taraması (pre-commit hook).
2. **Maliyet 0:** Yalnızca ücretsiz katman. Kota dolarsa turu atla, Telegram'dan bildir.
3. **Yalnızca resmi API:** Instagram API with Instagram Login. instagrapi/instaloader/tarayıcı otomasyonu YOK.
4. **İçerik/telif:** Haberler kendi cümleleriyle özetlenir, kaynak adı yazılır. Görsellerde logo, oyun karakteri, gerçek kişi, yazı yok — soyut arka plan.
   Arka planlar haberin konusunu anlatan sahneler (nesne/mekân/metafor); avatar, takvim, belge gibi yazı/figür çıkaran nesneler de yok.
   Caption sonu: "Görseller yapay zekâ ile üretilmiştir." Caption ≤2150 karakter.
5. **Disiplin:** Faz başında kısa plan → onay → uygula. Faz sonunda `pytest`, kabul kriterleri ✅/❌, `PROGRESS.md` güncelle, commit, **dur ve onay bekle**.
   Bir hata 2 denemede çözülmezse dur, neden + seçenekleri anlat. Ekran görüntüsü istemek yerine komutla doğrula.
6. **Yol:** Proje yolunda boşluk var ("Claude Projeler") → her yerde tırnak, göreli yol; kodda proje kökü `Path(__file__)` ile bulunur.

## Ortam
- Mac: Intel (x86_64), macOS 26.2, Homebrew `/usr/local`.
- Masaüstü iCloud ile **senkronize değil** (2026-11-13 kontrol edildi) → sanal ortam proje içinde `.venv`, `.env` proje kökünde.
- Python 3.12 (Homebrew `/usr/local/bin/python3.12`). Sanal ortam: `.venv` (proje içinde).
  Kullanım: `source .venv/bin/activate` veya doğrudan `.venv/bin/python -m bot ...`.
- Pre-commit: `git config core.hooksPath .githooks` → `scripts/secret_scan.sh` (gizli değer bulursa commit'i durdurur).
- gh hesabı: `hamamcioglutuncay-hub`.
- GitHub repo: `ig-tech-bot` (public). Yerel klasör: `ig_tech_bot`.

## Mimari (özet)
| İş | Araç |
|---|---|
| Haber | RSS/Atom (`feedparser`), `feeds.yaml` |
| Metin | Gemini API (`google-genai`), model `.env` → `LLM_MODEL` |
| Görsel arka plan | Cloudflare Workers AI `@cf/black-forest-labs/flux-1-schnell` |
| Kompozisyon | Pillow, 1080×1350 JPEG, `design.yaml` |
| Barındırma | Public repo raw URL (→ GitHub Pages → R2 yedek) |
| Çalıştırma | GitHub Actions cron |
| Önizleme | Telegram `sendMediaGroup` |
| Yayın | Instagram container → carousel → `media_publish` |

Modlar (`MODE`): `dry-run` → `approve` → `auto`.
Workflow'lar: `generate.yml` (05:07 İstanbul = 02:07 UTC + yedek 06:37 = 03:37 UTC), `publish.yml` (auto: 10:00 İstanbul = 07:00 UTC; approve: yalnızca manuel), `refresh-token.yml` (haftalık), `cleanup.yml` (30 gün).

## Komutlar
- `.venv/bin/python -m bot collect [--hours 24] [--limit 60|0] [--category oyun|teknoloji] [--include-seen]`
- `.venv/bin/python -m bot check [--no-telegram-test]`
- `.venv/bin/python -m bot write [--no-mark] [--images-only]`
- `.venv/bin/python -m bot render [--date YYYY-AA-GG] [--no-telegram] [--no-open]`
- `.venv/bin/python -m pytest -q`
- Paket kurulumu (Intel Mac): `.venv/bin/pip install --only-binary=:all: -r requirements.txt`

## Yapı
```
bot/ (config, collector, dedupe, llm_gemini, imagegen, composer, instagram, telegram, token_refresh, check, cli)
prompts/  design.yaml  feeds.yaml  assets/(fonts, logo.png, templates/)  state/  output/  logs/  tests/
.github/workflows/
```
