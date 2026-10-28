// Browser-Test der aunserver-Seite in Cockpit (VM-Test, M10 P3).
//
//   node dev/cockpit-test.mjs editor     <benutzer> <passwort> <ordner-für-bilder>
//   node dev/cockpit-test.mjs einrichten <benutzer> <passwort> <ordner-für-bilder> <seriennummer> <ssh-schlüssel>
//
// Erwartet Cockpit unter https://nas.home.arpa:9090 (VM-Weiterleitung auf localhost:9090; der Name
// wird im Browser auf 127.0.0.1 gelegt, damit der Origin zu cockpit.conf passt). Braucht
// playwright-core und Google Chrome (auf den GitHub-Runnern vorhanden).
//
// editor: anmelden, Seite laden, eine Einstellung ändern und speichern, die Änderung unter
// „Übernehmen“ und im Verlauf finden, Bilder ablegen.
// einrichten: Ersteinrichtung mit dem Assistenten wie im VM-Test über die Kommandozeile (Datenplatte
// über die Seriennummer, formatieren, PS2-Freigabe, Backup-Ziel), warten bis das Setup fertig ist.
// Keine JavaScript-Fehler erlaubt.
import { chromium } from "playwright-core";

const [modus, benutzer, passwort, bilder, seriennummer, sshSchluessel] = process.argv.slice(2);
const basis = "https://nas.home.arpa:9090";
const fehler = [];

const browser = await chromium.launch({
    channel: "chrome",
    args: ["--host-resolver-rules=MAP nas.home.arpa 127.0.0.1"],
});
const kontext = await browser.newContext({ ignoreHTTPSErrors: true, locale: "de-DE", viewport: { width: 1280, height: 900 } });
const seite = await kontext.newPage();
// Fehler erst ab der aunserver-Seite zählen: die Cockpit-Oberfläche selbst meldet vor dem ersten
// Setup (ohne cockpit-storaged usw.) gelegentlich einen eigenen Fehler
let eigeneSeite = false;
seite.on("pageerror", e => eigeneSeite && fehler.push(`pageerror (${new Date().toISOString()}): ${e.name}: ${e.message}\n${e.stack || ""}`));
// 401 gehört zur Anmeldeseite von Cockpit (Abfrage vor dem Login), kein Fehler der Seite
seite.on("console", m => {
    if (eigeneSeite && m.type() === "error" && !/status of 401 \(Authentication failed\)/.test(m.text())) fehler.push("console: " + m.text());
});

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
    eigeneSeite = true;
    await seite.goto(basis + "/cockpit/@localhost/aunserver/index.html");
    if (modus === "einrichten") await einrichten();
    else await editor();
} catch (ex) {
    await bild("fehler").catch(() => {});
    fehler.push(String(ex));
}
await browser.close();
if (fehler.length) {
    console.error(fehler.join("\n"));
    process.exit(1);
}
console.log(`Cockpit-Seite in Ordnung (${modus})`);

async function einrichten() {
    await seite.waitForSelector('#assistent input[name="platte"]', { timeout: 60000 });
    await bild("0-assistent");
    const platte = seite.locator(`#assistent input[name="platte"][data-serie="${seriennummer}"]`);
    await platte.check();
    const name = await platte.getAttribute("value");
    await seite.fill("#bestaetigung", name);
    await seite.fill("#a-hostname", "nas");
    await seite.fill("#a-ssh", sshSchluessel);
    await seite.fill("#a-samba", "ci-test-123");
    await seite.fill("#a-samba-2", "ci-test-123");
    await seite.locator('label:has(#a-ps2)').click();
    await seite.fill("#a-ps2pw", "ci-ps2-123");
    await seite.fill("#a-ps2pw-2", "ci-ps2-123");
    await seite.fill("#a-repo", "/var/backups/aunserver-ci");
    await bild("0-assistent-ausgefuellt");
    seite.on("dialog", d => d.accept());
    await seite.click("#assistent-start");
    await seite.waitForSelector("#ae-protokoll-karte:not([hidden])", { timeout: 60000 });
    // das Setup dauert; danach lädt die Seite neu, jetzt mit allen Reitern
    await seite.waitForSelector("#ae-status.gut, #ae-status.fehler", { timeout: 45 * 60000 });
    await bild("0-assistent-fertig");
    if (await seite.locator("#ae-status.fehler").count()) throw new Error("Einrichtung fehlgeschlagen: " + (await seite.textContent("#ae-protokoll")).slice(-3000));
    await seite.waitForSelector('[data-reiter="einstellungen"]:not([hidden])', { timeout: 60000 });
}

async function editor() {
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
}
