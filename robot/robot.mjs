// Robot Studio Konten: membuka situs tim di Chrome tanpa layar, masuk dengan akun robot,
// lalu menjalankan window.studioRobot() (logika otomasi ada di aplikasi itu sendiri).
//
// Variabel lingkungan:
//   SITUS_URL       alamat situs (bawaan: https://studio-konten.bmadam.workers.dev/)
//   ROBOT_EMAIL     email akun robot di Supabase
//   ROBOT_PASSWORD  kata sandi akun robot
//   ROBOT_TIRUAN=1  uji lokal dengan dev/server_uji.py (tanpa login)
//   CHROME_CHANNEL  bawaan "chrome" (Google Chrome terpasang); "chromium" untuk Chromium Playwright

import { chromium } from "playwright-core";

const SITUS = process.env.SITUS_URL || "https://studio-konten.bmadam.workers.dev/";
const TIRUAN = process.env.ROBOT_TIRUAN === "1";
const email = process.env.ROBOT_EMAIL || "";
const sandi = process.env.ROBOT_PASSWORD || "";

if (!TIRUAN && (!email || !sandi)) {
  console.error("ROBOT_EMAIL dan ROBOT_PASSWORD belum diatur (GitHub: Settings > Secrets and variables > Actions).");
  process.exit(1);
}

const browser = await chromium.launch({ channel: process.env.CHROME_CHANNEL || "chrome", headless: true });
let kode = 1;
try {
  // bypassCSP: header keamanan situs melarang eval, padahal Playwright memakainya untuk menunggu dan
  // memerintah halaman. Hanya berlaku untuk browser robot ini; pengunjung situs tetap terlindungi.
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, timezoneId: "Asia/Jakarta", locale: "id-ID", bypassCSP: true });
  // Repo publik: catatan Actions bisa dilihat siapa saja, jadi judul konten tidak dicetak di sini.
  // Catatan lengkap tersimpan di aplikasi (halaman Otomasi). ROBOT_RINCI=1 untuk mencetak semuanya.
  const rinci = process.env.ROBOT_RINCI === "1";
  page.on("console", (m) => {
    const t = m.text();
    if (t.startsWith("[robot]")) {
      const baris = t.slice(8);
      if (rinci || /^(GAGAL|Mode Manual|Tidak ada|Batas)/.test(baris)) console.log(baris);
    } else if (m.type() === "error" && rinci) console.log("(galat halaman) " + t);
  });
  page.on("pageerror", (e) => console.log("(galat halaman) " + e.message));
  await page.addInitScript(() => { window.STUDIO_ROBOT = true; });
  await page.goto(SITUS, { waitUntil: "load", timeout: 60000 });

  if (!TIRUAN) {
    await page.waitForFunction(() => typeof window.studioMasuk === "function", null, { timeout: 60000 });
    await page.evaluate(([e, s]) => window.studioMasuk(e, s), [email, sandi]);
  }
  await page.waitForFunction(() => window.studioSiap === true, null, { timeout: 90000 });
  await page.evaluate(() => document.fonts.ready);

  console.log(`Robot mulai: ${new Date().toISOString()}`);
  const hasil = await page.evaluate(() => window.studioRobot());
  console.log(`Robot selesai: ${hasil.ok ? "berhasil" : "GAGAL"} (${hasil.log.length} catatan; rincian di halaman Otomasi)`);
  kode = hasil.ok ? 0 : 1;
} catch (e) {
  console.error("Robot gagal dijalankan: " + (e && e.message ? e.message : e));
} finally {
  await browser.close();
}
process.exit(kode);
