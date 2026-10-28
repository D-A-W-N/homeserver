/* aunserver in Cockpit (D22): Einstellungen, Übernehmen, Verlauf, Passwörter.
 *
 * Die Seite schreibt nie selbst Dateien: alles geht über aunserver-config (prüft gegen das
 * Schema, Verlauf, Sperre) bzw. aunserver-setup als systemd-Unit (läuft weiter, auch wenn
 * das Fenster zu ist). Rechte: Cockpit mit Administratorzugriff (sudo).
 */
"use strict";

const CLI = "/usr/local/sbin/aunserver-config";
const SETUP = "/usr/local/sbin/aunserver-setup";
const UPDATE = "/usr/local/sbin/aunserver-update";
const EINHEIT = { setup: "aunserver-apply", update: "aunserver-update-run" };

const zustand = {
    schema: null,         // aunserver-config schema
    konfig: null,         // aunserver-config show --json
    entwurf: new Map(),   // Pfad -> {wert} oder {standard: true}
    ungueltig: new Map(), // Pfad -> {fehler, roh}: Eingabe, die sich nicht lesen ließ
    lauf: null,           // laufende Verfolgung eines Setup-/Update-Laufs
};

/* --- Hilfen --------------------------------------------------------------------------------- */

const $ = (sel, wurzel = document) => wurzel.querySelector(sel);

function el(tag, attrs = {}, ...kinder) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
        else if (v === true) e.setAttribute(k, "");
        else e.setAttribute(k, v);
    }
    for (const kind of kinder.flat()) {
        if (kind !== null && kind !== undefined && kind !== false)
            e.append(kind instanceof Node ? kind : document.createTextNode(String(kind)));
    }
    return e;
}

function holePfad(baum, pfad) {
    let knoten = baum;
    for (const teil of pfad.split(".")) {
        if (knoten === null || typeof knoten !== "object" || !(teil in knoten)) return undefined;
        knoten = knoten[teil];
    }
    return knoten;
}

function gleich(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
}

function zeigeWert(v) {
    if (v === undefined || v === null) return "(Standard)";
    if (typeof v === "string") return v === "" ? "''" : v;
    return JSON.stringify(v);
}

function cli(args, eingabe) {
    const proc = cockpit.spawn([CLI, ...args], { superuser: "require", err: "message" });
    if (eingabe !== undefined) proc.input(eingabe);
    return proc;
}

async function cliJson(args, eingabe) {
    return JSON.parse(await cli(args, eingabe));
}

function fehlertext(ex) {
    const text = (ex && (ex.message || ex.problem)) || String(ex);
    if (ex && ex.problem === "access-denied")
        return "Keine Berechtigung: oben rechts in Cockpit „Administratorzugriff“ einschalten.";
    return text.replace(/^Fehler: /gm, "");
}

function melde(text, art = "") {
    const box = $("#meldung");
    box.replaceChildren(el("span", { text }), el("button", { class: "klein", text: "Schließen", onclick: () => { box.hidden = true } }));
    box.className = "meldung " + art;
    box.hidden = false;
    if (art !== "fehler") box.scrollIntoView({ block: "nearest" });
}

/* --- Darstellung (hell/dunkel wie Cockpit) ------------------------------------------------------ */

function thema() {
    let stil = "auto";
    try {
        stil = window.localStorage.getItem("shell:style") || "auto";
    } catch (_) { /* ohne Speicher: wie das System */ }
    const dunkel = stil === "dark" || (stil === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dunkel", dunkel);
}

/* --- Reiter ---------------------------------------------------------------------------------- */

function zeigeReiter(name) {
    for (const knopf of document.querySelectorAll("[data-reiter]"))
        knopf.setAttribute("aria-selected", String(knopf.dataset.reiter === name));
    for (const seite of document.querySelectorAll(".seite"))
        seite.hidden = seite.id !== name;
    cockpit.location.go([name]);
    const laden = { uebersicht: ladeUebersicht, aenderungen: ladeAenderungen, verlauf: ladeVerlauf, passwoerter: zeigePasswoerter };
    if (laden[name]) laden[name]().catch(ex => melde(fehlertext(ex), "fehler"));
}

/* --- Laden ----------------------------------------------------------------------------------- */

async function ladeKonfig() {
    zustand.konfig = await cliJson(["show", "--json"]);
    const diff = await cliJson(["diff", "--json"]);
    const zaehler = $("#zaehler");
    zaehler.textContent = String(diff.aenderungen.length);
    zaehler.hidden = diff.aenderungen.length === 0;
    return diff;
}

async function ladeUebersicht() {
    const diff = await ladeKonfig();
    const k = zustand.konfig;
    const befunde = $("#ue-befunde");
    befunde.replaceChildren(
        ...k.fehler.map(t => el("p", { class: "befund fehler", text: "Fehler: " + t })),
        ...k.warnungen.map(t => el("p", { class: "befund warn", text: "Warnung: " + t })));
    $("#ue-konfig").textContent = k.fehler.length
        ? "Die config.yml hat Fehler, das Setup würde abbrechen."
        : diff.aenderungen.length
            ? `${diff.aenderungen.length} Änderung(en) noch nicht übernommen.`
            : "Alles übernommen.";

    const commit = await cockpit.file("/opt/aunserver/COMMIT").read().catch(() => "");
    const kurz = (commit || "").trim().split(/\s+/)[0] || "";
    const version = /^[0-9a-f]{40}$/.test(kurz) ? kurz.slice(0, 7) : "Entwicklungsstand";
    $("#version").textContent = version;
    $("#ue-version").textContent = `Installiert: ${version}`;

    const lauf = await laufStatus(EINHEIT.setup);
    const zuletzt = await cockpit.spawn(["stat", "-c", "%Y", "/var/lib/aunserver/config.angewendet.yml"],
        { superuser: "require", err: "ignore" }).catch(() => "");
    const wann = /^\d+/.test(zuletzt) ? new Date(Number(zuletzt.trim()) * 1000).toLocaleString("de-DE") : null;
    $("#ue-lauf").textContent = lauf.aktiv ? "Ein Lauf ist gerade aktiv."
        : lauf.fehlgeschlagen ? "Der letzte Lauf aus dem Browser ist fehlgeschlagen."
            : wann ? `Zuletzt erfolgreich übernommen: ${wann}` : "Noch kein erfolgreicher Lauf vermerkt.";
}

/* --- Einstellungen --------------------------------------------------------------------------- */

function eintragTyp(spec) {
    return spec.eintrag || "text";
}

// Wert für das Eingabefeld und zurück; Listen einfacher Werte zeilenweise, Blöcke als JSON
function alsText(spec, wert) {
    if (spec.typ === "liste" && !["objekt", "liste"].includes(eintragTyp(spec)))
        return (wert || []).join("\n");
    if (spec.typ === "liste" || spec.typ === "objekt")
        return JSON.stringify(wert ?? (spec.typ === "liste" ? [] : {}), null, 2);
    return wert === undefined || wert === null ? "" : String(wert);
}

function ausText(spec, text) {
    if (spec.typ === "zahl") {
        if (!/^-?\d+$/.test(text.trim())) throw new Error("Ganze Zahl erwartet");
        return Number(text.trim());
    }
    if (spec.typ === "liste" && !["objekt", "liste"].includes(eintragTyp(spec))) {
        const zeilen = text.split("\n").map(z => z.trim()).filter(z => z !== "");
        if (eintragTyp(spec) === "zahl") {
            if (zeilen.some(z => !/^-?\d+$/.test(z))) throw new Error("Eine ganze Zahl pro Zeile");
            return zeilen.map(Number);
        }
        return zeilen;
    }
    if (spec.typ === "liste" || spec.typ === "objekt") {
        let wert;
        try {
            wert = JSON.parse(text || (spec.typ === "liste" ? "[]" : "{}"));
        } catch (ex) {
            throw new Error("Kein gültiges JSON: " + ex.message);
        }
        if (spec.typ === "liste" && !Array.isArray(wert)) throw new Error("Liste in [ ] erwartet");
        if (spec.typ === "objekt" && (wert === null || Array.isArray(wert) || typeof wert !== "object"))
            throw new Error("Block in { } erwartet");
        return wert;
    }
    return text;
}

function wirksam(pfad) {
    const e = zustand.entwurf.get(pfad);
    if (e) return e.standard ? zustand.schema.einstellungen[pfad].standard : e.wert;
    return holePfad(zustand.konfig.wirksam, pfad);
}

function istEigen(pfad) {
    const e = zustand.entwurf.get(pfad);
    if (e) return !e.standard;
    return holePfad(zustand.konfig.eigene, pfad) !== undefined;
}

// Entwurf merken; gleicht er dem gespeicherten Stand, ist es keine Änderung mehr
function setzeEntwurf(pfad, eintrag) {
    const unveraendert = eintrag.standard
        ? holePfad(zustand.konfig.eigene, pfad) === undefined
        : gleich(eintrag.wert, holePfad(zustand.konfig.wirksam, pfad));
    if (unveraendert) zustand.entwurf.delete(pfad);
    else zustand.entwurf.set(pfad, eintrag);
    aktualisiereLeiste();
}

function aktualisiereLeiste() {
    const n = zustand.entwurf.size;
    const fehler = zustand.ungueltig.size;
    $("#speicherleiste").hidden = n === 0 && fehler === 0;
    $("#speicher-text").textContent = fehler
        ? `${fehler} Eingabe(n) ungültig`
        : `${n} ungespeicherte Änderung(en)`;
    $("#speichern").disabled = fehler > 0 || n === 0;
}

function eingabeFuer(pfad, spec, wert, gesperrt) {
    const id = "f-" + pfad.replace(/\W/g, "-");
    const bei = (lesen) => (ev) => {
        let neu;
        try {
            neu = lesen(ev.target);
            zustand.ungueltig.delete(pfad);
        } catch (ex) {
            zustand.ungueltig.set(pfad, { fehler: ex.message, roh: ev.target.value });
            zeichneFeld(pfad);
            aktualisiereLeiste();
            return;
        }
        setzeEntwurf(pfad, { wert: neu });
        zeichneFeld(pfad);
    };
    if (spec.typ === "bool") {
        return el("label", { class: "schalter" },
            el("input", { type: "checkbox", id, checked: wert === true, disabled: gesperrt, onchange: bei(t => t.checked) }),
            el("span", { class: "bahn" }),
            el("span", { text: wert ? "an" : "aus" }));
    }
    if (spec.typ === "auswahl") {
        return el("select", { id, disabled: gesperrt, onchange: bei(t => t.value) },
            spec.werte.map(w => el("option", { value: w, selected: w === wert, text: w })));
    }
    if (spec.typ === "liste" || spec.typ === "objekt") {
        const ta = el("textarea", { id, disabled: gesperrt, spellcheck: "false", onchange: bei(t => ausText(spec, t.value)) });
        ta.value = zustand.ungueltig.has(pfad) ? zustand.ungueltig.get(pfad).roh : alsText(spec, wert);
        ta.rows = Math.min(12, Math.max(2, ta.value.split("\n").length));
        return ta;
    }
    const eingabe = el("input", {
        id, type: spec.typ === "zahl" ? "number" : "text", disabled: gesperrt, min: spec.min, max: spec.max,
        placeholder: { zeit: "HH:MM", ip: "z. B. 192.168.1.10", netz: "z. B. 192.168.1.0/24" }[spec.format] || "",
        onchange: bei(t => ausText(spec, t.value)),
    });
    eingabe.value = zustand.ungueltig.has(pfad) ? zustand.ungueltig.get(pfad).roh : alsText(spec, wert);
    return eingabe;
}

// Wird das Feld mit dem Fokus entfernt, feuert der Browser dabei noch einmal "change"
// (blur) und wir kämen hier verschachtelt wieder an: dann nicht doppelt ersetzen
let zeichneGerade = false;
function zeichneFeld(pfad) {
    if (zeichneGerade) return;
    zeichneGerade = true;
    try {
        const alt = document.querySelector(`[data-pfad="${CSS.escape(pfad)}"]`);
        if (alt && alt.isConnected) alt.replaceWith(feld(pfad));
    } finally {
        zeichneGerade = false;
    }
}

function feld(pfad) {
    const spec = zustand.schema.einstellungen[pfad];
    const wert = wirksam(pfad);
    const fest = spec.stufe === "fest";
    const braucht = spec.braucht && wirksam(spec.braucht) !== true;
    const eigen = istEigen(pfad);
    const ungespeichert = zustand.entwurf.has(pfad);
    const fehler = (zustand.ungueltig.get(pfad) || {}).fehler;

    const marke = fest
        ? el("span", { class: "marke", text: "setzt das Setup" })
        : eigen ? el("span", { class: "marke eigen", text: "eigener Wert" }) : el("span", { class: "marke", text: "Standard" });
    const zuruecksetzen = !fest && eigen
        ? el("button", {
            class: "klein", text: "Auf Standard",
            title: "Standard: " + zeigeWert(spec.standard),
            onclick: () => { zustand.ungueltig.delete(pfad); setzeEntwurf(pfad, { standard: true }); zeichneFeld(pfad) },
        })
        : null;
    const rueckgaengig = ungespeichert
        ? el("button", {
            class: "klein", text: "Rückgängig",
            onclick: () => { zustand.entwurf.delete(pfad); zustand.ungueltig.delete(pfad); aktualisiereLeiste(); zeichneFeld(pfad) },
        })
        : null;

    return el("div", {
        class: "feld" + (ungespeichert ? " ungespeichert" : "") + (braucht ? " ohne-wirkung" : ""),
        "data-pfad": pfad, "data-stufe": spec.stufe,
    },
    el("div", { class: "feld-text" },
        el("label", { for: "f-" + pfad.replace(/\W/g, "-"), text: spec.text }),
        el("span", { class: "pfad", text: pfad }),
        spec.hinweis ? el("span", { class: "hinweis", text: spec.hinweis }) : null,
        braucht ? el("span", { class: "hinweis", text: `Wirkt nur mit ${spec.braucht}.` }) : null),
    el("div", { class: "eingabe" },
        eingabeFuer(pfad, spec, wert, fest),
        fehler ? el("span", { class: "fehler-text", text: fehler }) : null,
        el("span", { class: "zeile" }, marke, zuruecksetzen, rueckgaengig)));
}

function zeichneFormular() {
    const s = zustand.schema;
    const suche = $("#suche").value.trim().toLowerCase();
    const erweitert = $("#erweitert").checked;
    const teile = [];
    for (const [bereich, titel] of Object.entries(s.bereiche)) {
        const pfade = Object.keys(s.einstellungen).filter(p => {
            const spec = s.einstellungen[p];
            if (spec.bereich !== bereich || spec.geheim || p === "config_version") return false;
            if (suche) return (p + " " + spec.text + " " + (spec.hinweis || "")).toLowerCase().includes(suche);
            return erweitert || spec.stufe === "basis" || istEigen(p) || zustand.entwurf.has(p);
        });
        if (pfade.length)
            teile.push(el("section", { class: "bereich" }, el("h2", { text: titel }), pfade.map(feld)));
    }
    $("#formular").replaceChildren(...(teile.length ? teile : [el("p", { class: "leise", text: "Keine passende Einstellung." })]));
}

async function ladeEinstellungen() {
    zustand.schema = zustand.schema || await cliJson(["schema"]);
    await ladeKonfig();
    zustand.entwurf.clear();
    zustand.ungueltig.clear();
    aktualisiereLeiste();
    zeichneFormular();
}

async function speichern() {
    const anfrage = { set: {}, unset: [], grund: "Cockpit (" + (cockpit.info.user || "Admin") + ")" };
    for (const [pfad, e] of zustand.entwurf) {
        if (e.standard) anfrage.unset.push(pfad);
        else anfrage.set[pfad] = e.wert;
    }
    $("#speichern").disabled = true;
    try {
        const antwort = await cliJson(["edit"], JSON.stringify(anfrage));
        await ladeEinstellungen();
        const box = $("#meldung");
        melde(`Gespeichert (Fassung ${antwort.fassung}). Wirksam wird es mit „Übernehmen“.`, "gut");
        box.insertBefore(el("button", { class: "primaer", text: "Jetzt übernehmen", onclick: () => { box.hidden = true; zeigeReiter("aenderungen"); starteLauf("setup") } }), box.lastChild);
    } catch (ex) {
        melde("Nicht gespeichert:\n" + fehlertext(ex), "fehler");
        aktualisiereLeiste();
    }
}

/* --- Übernehmen (Setup als systemd-Unit) ------------------------------------------------------ */

async function ladeAenderungen() {
    const diff = await ladeKonfig();
    $("#ae-titel").textContent = diff.aenderungen.length ? diff.titel : "Alles übernommen";
    $("#ae-liste").replaceChildren(diff.aenderungen.length
        ? el("table", { class: "tabelle" },
            el("thead", {}, el("tr", {}, el("th", { text: "Einstellung" }), el("th", { text: "Bisher" }), el("th", { text: "Neu" }))),
            el("tbody", {}, diff.aenderungen.map(a => el("tr", {},
                el("td", { class: "wert", text: a.pfad }), el("td", { class: "wert", text: zeigeWert(a.alt) }),
                el("td", { class: "wert", text: zeigeWert(a.neu) })))))
        : el("p", { class: "leise", text: "Die Konfiguration entspricht dem letzten Lauf. Übernehmen gleicht das System trotzdem neu ab." }));
    $("#uebernehmen").disabled = zustand.konfig.fehler.length > 0;
    const status = await laufStatus(EINHEIT.setup);
    if (status.aktiv && !zustand.lauf) verfolge("setup", status.invocation);
}

async function systemctlShow(einheit) {
    const aus = await cockpit.spawn(["systemctl", "show", einheit, "-p", "ActiveState,Result,InvocationID,ExecMainExitTimestamp"],
        { superuser: "require", err: "message" });
    const werte = {};
    for (const zeile of aus.split("\n")) {
        const i = zeile.indexOf("=");
        if (i > 0) werte[zeile.slice(0, i)] = zeile.slice(i + 1);
    }
    return werte;
}

async function laufStatus(einheit) {
    const w = await systemctlShow(einheit);
    const aktiv = ["active", "activating", "reloading"].includes(w.ActiveState);
    return { aktiv, fehlgeschlagen: w.ActiveState === "failed", invocation: w.InvocationID };
}

async function starteLauf(art) {
    const einheit = EINHEIT[art];
    if (zustand.lauf) return;
    const status = await laufStatus(einheit);
    if (status.aktiv) return verfolge(art, status.invocation);
    const admin = (zustand.konfig && zustand.konfig.wirksam.admin_user) || "nasadmin";
    const befehl = art === "setup" ? [SETUP, "--yes"] : [UPDATE, "--yes"];
    await cockpit.spawn(["systemctl", "reset-failed", einheit], { superuser: "require", err: "ignore" }).catch(() => {});
    try {
        // eigene Unit: läuft weiter, wenn das Fenster zu ist; SUDO_USER wie bei "sudo aunserver-setup"
        await cockpit.spawn(["systemd-run", "--unit=" + einheit, "--description=aunserver: " + (art === "setup" ? "übernehmen" : "aktualisieren"),
            "--property=Type=exec", "--setenv=SUDO_USER=" + admin, "--setenv=TERM=dumb", ...befehl],
        { superuser: "require", err: "message" });
    } catch (ex) {
        melde("Konnte nicht starten:\n" + fehlertext(ex), "fehler");
        return;
    }
    const neu = await systemctlShow(einheit);
    verfolge(art, neu.InvocationID);
}

function verfolge(art, invocation) {
    const einheit = EINHEIT[art];
    const ziel = art === "setup" ? $("#ae-protokoll") : $("#ue-update");
    const marke = $("#ae-status");
    if (art === "setup") {
        $("#ae-protokoll-karte").hidden = false;
        marke.className = "marke warn";
        marke.textContent = "läuft …";
        $("#uebernehmen").disabled = true;
    } else {
        ziel.hidden = false;
        $("#update-starten").disabled = true;
    }
    ziel.textContent = "";
    const args = invocation ? ["journalctl", "_SYSTEMD_INVOCATION_ID=" + invocation, "-f", "-o", "cat"]
        : ["journalctl", "-u", einheit, "-f", "-o", "cat", "-n", "200"];
    const leser = cockpit.spawn(args, { superuser: "require", err: "out" });
    leser.stream(daten => {
        ziel.textContent += daten;
        ziel.scrollTop = ziel.scrollHeight;
    });
    leser.catch(() => {});
    zustand.lauf = { art, leser };
    const takt = window.setInterval(async () => {
        let w;
        try {
            w = await systemctlShow(einheit);
        } catch (_) {
            return;
        }
        if (["active", "activating", "reloading"].includes(w.ActiveState)) return;
        window.clearInterval(takt);
        window.setTimeout(() => leser.close(), 1500);   // letzte Zeilen noch lesen
        zustand.lauf = null;
        const ok = w.ActiveState !== "failed" && /== (Fertig|Update fertig)/.test(ziel.textContent);
        if (art === "setup") {
            marke.className = "marke " + (ok ? "gut" : "fehler");
            marke.textContent = ok ? "fertig" : "fehlgeschlagen";
            $("#uebernehmen").disabled = false;
            ladeAenderungen().catch(() => {});
        } else {
            $("#update-starten").disabled = false;
        }
        melde(ok ? (art === "setup" ? "Übernommen." : "Aktualisiert.")
            : "Der Lauf ist fehlgeschlagen, Einzelheiten im Protokoll (auch /var/log/aunserver-setup.log).", ok ? "gut" : "fehler");
    }, 2000);
}

/* --- Verlauf ----------------------------------------------------------------------------------- */

function fassungLesbar(f) {
    const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(f);
    return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}:${m[6]}` : f;
}

async function ladeVerlauf() {
    const liste = await cliJson(["history", "--json"]);
    $("#vl-liste").replaceChildren(...(liste.length ? liste.map((e, i) => el("div", { class: "verlauf-eintrag" },
        el("div", { class: "verlauf-kopf" },
            el("span", {}, el("strong", { text: fassungLesbar(e.fassung) }), " ", el("span", { class: "leise", text: e.grund })),
            i === 0 ? el("span", { class: "marke eigen", text: "aktuell" })
                : el("button", { class: "sekundaer", text: "Zurückholen", onclick: () => zurueckholen(e) })),
        e.aenderungen.length ? el("ul", { class: "verlauf-aend" },
            e.aenderungen.map(a => el("li", {}, el("code", { text: a.pfad }), ": ", zeigeWert(a.alt), " → ", zeigeWert(a.neu)))) : null))
        : [el("p", { class: "leise", text: "Noch keine Fassungen." })]));
}

async function zurueckholen(eintrag) {
    if (!window.confirm(`Fassung vom ${fassungLesbar(eintrag.fassung)} zurückholen? Danach übernehmen.`)) return;
    try {
        await cli(["revert", eintrag.fassung]);
        melde(`Fassung vom ${fassungLesbar(eintrag.fassung)} zurückgeholt. Wirksam wird sie mit „Übernehmen“.`, "gut");
        await ladeVerlauf();
        await ladeKonfig();
    } catch (ex) {
        melde(fehlertext(ex), "fehler");
    }
}

/* --- Passwörter -------------------------------------------------------------------------------- */

async function zeigePasswoerter() {
    if (!zustand.konfig) await ladeKonfig();
    const w = zustand.konfig.wirksam;
    const karten = [
        { art: "samba", titel: "Samba-Freigaben", text: `Konto ${w.admin_user} für \\\\nas\\… im Netz. Gilt sofort.` },
        {
            art: "ps2", titel: "PS2-Freigabe", text: "Konto ps2 der SMB1-Freigabe. SMB1 schützt es schwach: kein wichtiges Passwort. Gilt sofort.",
            aus: !(w.samba_legacy && w.samba_legacy.enabled) && "Die PS2-Freigabe ist aus.",
        },
        {
            art: "web", titel: "Web-Passwort",
            text: `Anmeldung ${w.admin_user} an Caddy (Logs, Platten, SABnzbd …), AdGuard, Beszel und den Servarr-Apps. Wirksam nach „Übernehmen“.`,
        },
    ];
    $("#pw-karten").replaceChildren(...karten.map(k => {
        const eins = el("input", { type: "password", autocomplete: "new-password", disabled: !!k.aus });
        const zwei = el("input", { type: "password", autocomplete: "new-password", disabled: !!k.aus });
        const knopf = el("button", { class: "primaer", text: "Ändern", disabled: !!k.aus });
        const form = el("form", { class: "pw-form" },
            el("label", {}, "Neues Passwort", eins), el("label", {}, "Wiederholen", zwei), el("div", { class: "knoepfe" }, knopf));
        form.addEventListener("submit", async ev => {
            ev.preventDefault();
            if (eins.value !== zwei.value) return melde("Die Passwörter stimmen nicht überein.", "fehler");
            knopf.disabled = true;
            try {
                await cli(["passwd", k.art, "--stdin"], eins.value + "\n");
                eins.value = zwei.value = "";
                melde(k.art === "web" ? "Web-Passwort gespeichert. Wirksam wird es mit „Übernehmen“." : "Passwort geändert.", "gut");
            } catch (ex) {
                melde(fehlertext(ex), "fehler");
            } finally {
                knopf.disabled = false;
            }
        });
        return el("article", { class: "karte" }, el("h2", { text: k.titel }), el("p", { class: "leise", text: k.aus || k.text }), form);
    }));
}

/* --- Updates und Zugänge ----------------------------------------------------------------------- */

async function updatePruefen() {
    const knopf = $("#update-pruefen");
    const ausgabe = $("#ue-update");
    knopf.disabled = true;
    ausgabe.hidden = false;
    ausgabe.textContent = "Frage GitHub …";
    // Rückgabe 10 heißt „neuer Stand verfügbar“; die Ausgabe (Liste der Änderungen) kommt dann
    // als zweites Argument der Fehlerbehandlung
    const ergebnis = await new Promise(fertig => {
        cockpit.spawn([UPDATE, "--check"], { superuser: "require", err: "message" })
            .then(aus => fertig({ rc: 0, aus }), (ex, aus) => fertig({ rc: ex.exit_status, aus, ex }));
    });
    knopf.disabled = false;
    $("#update-starten").hidden = ergebnis.rc !== 10;
    ausgabe.textContent = ergebnis.rc === 0 || ergebnis.rc === 10 ? ergebnis.aus : fehlertext(ergebnis.ex);
}

async function zugaengeZeigen() {
    const text = await cockpit.file("/etc/aunserver/zugaenge.txt", { superuser: "require" }).read();
    const pre = $("#zg-text");
    pre.textContent = text || "Noch keine Zugangsübersicht (erst nach dem ersten Setup).";
    pre.hidden = false;
}

/* --- Start ------------------------------------------------------------------------------------- */

function start() {
    thema();
    window.addEventListener("storage", ev => { if (ev.key === "shell:style") thema() });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", thema);

    for (const knopf of document.querySelectorAll("[data-reiter]"))
        knopf.addEventListener("click", () => zeigeReiter(knopf.dataset.reiter));
    for (const knopf of document.querySelectorAll("[data-gehe]"))
        knopf.addEventListener("click", () => zeigeReiter(knopf.dataset.gehe));
    $("#suche").addEventListener("input", zeichneFormular);
    $("#erweitert").addEventListener("change", zeichneFormular);
    $("#verwerfen").addEventListener("click", () => { zustand.entwurf.clear(); zustand.ungueltig.clear(); aktualisiereLeiste(); zeichneFormular() });
    $("#speichern").addEventListener("click", speichern);
    $("#uebernehmen").addEventListener("click", () => starteLauf("setup"));
    $("#update-pruefen").addEventListener("click", updatePruefen);
    $("#update-starten").addEventListener("click", () => {
        if (window.confirm("Jetzt aktualisieren? Vorher läuft ein Backup, danach das Setup.")) starteLauf("update");
    });
    $("#zg-zeigen").addEventListener("click", () => zugaengeZeigen().catch(ex => melde(fehlertext(ex), "fehler")));
    window.addEventListener("beforeunload", ev => {
        if (zustand.entwurf.size) {
            ev.preventDefault();
            ev.returnValue = "";
        }
    });

    const ziel = cockpit.location.path[0];
    ladeEinstellungen()
        .then(() => zeigeReiter(document.getElementById(ziel) ? ziel : "uebersicht"))
        .catch(ex => melde(fehlertext(ex), "fehler"));
}

document.addEventListener("DOMContentLoaded", start);
