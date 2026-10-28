// Browser-Test der aunserver-Seite in Cockpit (VM-Test, M10 P3).
//
//   node dev/cockpit-test.mjs <benutzer> <passwort> <ordner-für-bilder>
//
// Erwartet Cockpit unter https://nas.home.arpa:9090 (VM-Weiterleitung auf localhost:9090; der Name
// wird im Browser auf 127.0.0.1 gelegt, damit der Origin zu cockpit.conf passt). Braucht
// playwright-core und Google Chrome (auf den GitHub-Runnern vorhanden).
//
// Ablauf: anmelden, Seite laden, eine Einstellung ändern und speichern, die Änderung unter
// „Übernehmen“ und im Verlauf finden, Bilder ablegen. Keine JavaScript-Fehler erlaubt.
import { chromium } from "playwright-core";

const [benutzer, passwort, bilder] = process.argv.slice(2);
const basis = "https://nas.home.arpa:9090";
const fehler = [];

const browser = await chromium.launch({
    channel: "chrome",
    args: ["--host-resolver-rules=MAP nas.home.arpa 127.0.0.1"],
});
const kontext = await browser.newContext({ ignoreHTTPSErrors: true, locale: "de-DE", viewport: { width: 1280, height: 900 } });
const seite = await kontext.newPage();
seite.on("pageerror", e => fehler.push("pageerror: " + e.message));
seite.on("console", m => { if (m.type() === "error") fehler.push("console: " + m.text()) });

// Rückfall, falls Cockpit trotzdem eingeschränkt startet: oben rechts umschalten
async function adminZugriff() {
    const knopf = seite.locator("#super-user-indicator button, #super-user-indicator-mobile button").first();
    if (!(await knopf.count()) || !/eingeschränkt|limited/i.test(await knopf.textContent())) return;
    await knopf.click();
    const dialog = seite.locator('[role="dialog"]');
    await dialog.locator('input[type="password"]').fill(passwort);
    await dialog.locator('button.pf-m-primary, button[type="submit"]').first().click();
    await seite.waitForTimeout(3000);
}

async function bild(name) {
    await seite.screenshot({ path: `${bilder}/${name}.png`, fullPage: true });
}

try {
    await seite.goto(basis + "/");
    // Administratorzugriff gleich bei der Anmeldung (wie „Administratorzugriff“ einschalten);
    // eine frische Browser-Sitzung startet sonst eingeschränkt
    await seite.evaluate(u => localStorage.setItem("superuser:" + u, "any"), benutzer);
    await seite.fill("#login-user-input", benutzer);
    await seite.fill("#login-password-input", passwort);
    await seite.click("#login-button");
    await seite.waitForURL(/\/system|\/cockpit|\/$/, { timeout: 30000 });
    await seite.waitForTimeout(3000);   // Shell und Administratorzugriff starten
    await adminZugriff();

    // die Seite direkt, ohne Cockpit-Rahmen (cockpit.js verbindet sich selbst)
    await seite.goto(basis + "/cockpit/@localhost/aunserver/index.html");
    await seite.waitForSelector("#version:not(:empty)", { timeout: 60000 });
    await bild("1-uebersicht");

    await seite.click('[data-reiter="einstellungen"]');
    await seite.waitForSelector('[data-pfad="apps.emby"]');
    await seite.check("#erweitert");
    const feld = seite.locator('[data-pfad="ntfy_ios_push"]');
    await feld.locator(".schalter").click();
    await seite.waitForSelector("#speicherleiste:not([hidden])");
    await bild("2-einstellungen-entwurf");
    await seite.click("#speichern");
    await seite.waitForSelector("#meldung.gut", { timeout: 30000 });
    if (!(await feld.locator(".marke.eigen").count())) throw new Error("ntfy_ios_push nach dem Speichern nicht als eigener Wert markiert");

    await seite.click('[data-reiter="aenderungen"]');
    await seite.waitForSelector("#ae-liste table");
    const tabelle = await seite.textContent("#ae-liste");
    if (!tabelle.includes("ntfy_ios_push")) throw new Error("Änderung fehlt unter „Übernehmen“: " + tabelle);
    await bild("3-uebernehmen");

    await seite.click('[data-reiter="verlauf"]');
    await seite.waitForSelector(".verlauf-eintrag");
    const verlauf = await seite.textContent("#vl-liste");
    if (!verlauf.includes("Cockpit")) throw new Error("Verlauf ohne den Eintrag aus Cockpit: " + verlauf);
    await bild("4-verlauf");

    await seite.click('[data-reiter="passwoerter"]');
    await seite.waitForSelector("#pw-karten .karte");
    await bild("5-passwoerter");

    // ungültige Eingabe: Fehlertext, Speichern gesperrt
    await seite.click('[data-reiter="einstellungen"]');
    const ports = seite.locator('[data-pfad="stacks_lan_ports"] textarea');
    await ports.fill("{kaputt");
    await ports.dispatchEvent("change");
    await seite.waitForSelector('[data-pfad="stacks_lan_ports"] .fehler-text');
    if (!(await seite.isDisabled("#speichern"))) throw new Error("Speichern trotz ungültiger Eingabe möglich");
    await seite.click("#verwerfen");

    // dunkle Darstellung wie in Cockpit
    await seite.evaluate(() => { localStorage.setItem("shell:style", "dark"); window.dispatchEvent(new StorageEvent("storage", { key: "shell:style" })) });
    await bild("6-einstellungen-dunkel");
} catch (ex) {
    await bild("fehler").catch(() => {});
    fehler.push(String(ex));
}
await browser.close();
if (fehler.length) {
    console.error(fehler.join("\n"));
    process.exit(1);
}
console.log("Cockpit-Seite in Ordnung");
