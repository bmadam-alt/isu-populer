// Robot Studio Konten: membuka situs tim di Chrome tanpa layar, masuk dengan akun robot,
// lalu menjalankan window.studioRobot() (logika otomasi ada di aplikasi itu sendiri).
//
// Variabel lingkungan:
//   SITUS_URL       alamat situs (bawaan: https://studio-konten.bmadam.workers.dev/)
//   ROBOT_EMAIL     email akun robot di Supabase
//   ROBOT_PASSWORD  kata sandi akun robot
//   ROBOT_TIRUAN=1  uji lokal dengan dev/server_uji.py (tanpa login)
//   CHROME_CHANNEL  bawaan "chrome" (Google Chrome terpasang); "bawaan" untuk Chromium Playwright

import { chromium } from "playwright-core";

const SITUS = process.env.SITUS_URL || "https://studio-konten.bmadam.workers.dev/";
const TIRUAN = process.env.ROBOT_TIRUAN === "1";
const email = process.env.ROBOT_EMAIL || "";
const sandi = process.env.ROBOT_PASSWORD || "";

if (!TIRUAN && (!email || !sandi)) {
  console.error("ROBOT_EMAIL dan ROBOT_PASSWORD belum diatur (GitHub: Settings > Secrets and variables > Actions).");
  process.exit(1);
}

// CHROME_CHANNEL="bawaan": Chromium bawaan Playwright (server tanpa Google Chrome, mis. ARM)
const kanal = process.env.CHROME_CHANNEL || "chrome";
const browser = await chromium.launch({ ...(kanal === "bawaan" ? {} : { channel: kanal }), headless: true });
let kode = 1;
// Repo publik: catatan Actions bisa dilihat siapa saja, jadi judul konten dan galat halaman tidak dicetak.
// Catatan lengkap tersimpan di aplikasi (halaman Otomasi). ROBOT_RINCI=1 untuk mencetak semuanya.
const rinci = process.env.ROBOT_RINCI === "1";
const tunggu = (ms) => new Promise((r) => setTimeout(r, ms));
// Menunggu kondisi di halaman dengan page.evaluate berulang (lewat protokol debugging Chrome, tidak
// memerlukan eval di halaman), sehingga header keamanan (CSP) situs tetap berlaku untuk sesi robot.
async function tungguKondisi(page, fn, batasMs) {
  const akhir = Date.now() + batasMs;
  while (Date.now() < akhir) {
    if (await page.evaluate(fn)) return;
    await tunggu(500);
  }
  throw new Error("Waktu tunggu halaman habis.");
}
async function jalankan(bypassCSP) {
  // bypassCSP hanya dipakai bila cara aman di atas ditolak browser (cadangan); pengunjung situs tidak terpengaruh.
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, timezoneId: "Asia/Jakarta", locale: "id-ID", bypassCSP });
  page.on("console", (m) => {
    const t = m.text();
    if (t.startsWith("[robot]")) {
      const baris = t.slice(8);
      if (rinci || /^(GAGAL|Mode Manual|Tidak ada|Batas)/.test(baris)) console.log(baris);
    } else if (m.type() === "error" && rinci) console.log("(galat halaman) " + t);
  });
  page.on("pageerror", (e) => { if (rinci) console.log("(galat halaman) " + e.message); });
  await page.addInitScript(() => { window.STUDIO_ROBOT = true; });
  await page.goto(SITUS, { waitUntil: "load", timeout: 60000 });
  if (!TIRUAN) {
    await tungguKondisi(page, () => typeof window.studioMasuk === "function", 60000);
    await page.evaluate(([e, s]) => window.studioMasuk(e, s), [email, sandi]);
  }
  await tungguKondisi(page, () => window.studioSiap === true, 90000);
  await page.evaluate(() => document.fonts.ready);
  return page;
}
try {
  let page;
  try { page = await jalankan(false); }
  catch (e) {
    const pesan = String((e && e.message) || e);
    if (!/unsafe-eval|Content Security Policy|EvalError/i.test(pesan)) throw e;
    console.log("Header keamanan situs menolak alat robot; mengulang dengan pengecualian CSP khusus browser robot.");
    page = await jalankan(true);
  }
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
