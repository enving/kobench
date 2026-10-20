"""Anbindung an Sprachmodelle: Chat (mit Werkzeugen) und Embeddings, anbieterneutral.

Alles kommt aus Umgebungsvariablen (oder einer `.env` im Projektordner, siehe `.env.example`).
Schlüssel werden nie ausgegeben.

Anbieter (`KOBENCH_ANBIETER`, für den Richter getrennt `KOBENCH_RICHTER_ANBIETER`):
  openai      jeder OpenAI-kompatible Endpunkt: OpenAI, Ollama, LM Studio, vLLM, OpenRouter, IONOS …
              (`KOBENCH_BASE_URL`, `KOBENCH_API_KEY`)
  mistral     Mistral La Plateforme (`MISTRAL_API_KEY`)
  anthropic   Claude über die Messages-API (`ANTHROPIC_API_KEY`)
  claude-cli  Claude über die Claude-Code-CLI (`claude -p`, nutzt ein vorhandenes Abo, kein Schlüssel)

Embeddings (für Hybrid, Kundenakte, Agent) laufen immer über einen OpenAI-kompatiblen
`/embeddings`-Endpunkt (`KOBENCH_EMBED_*`); Anthropic hat keinen eigenen.
"""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("KOBENCH_CACHE") or Path.cwd() / ".cache")
SEED = 88501028


def _env_datei():
    """`.env` im Projektordner einlesen (ohne Abhängigkeit), echte Umgebungsvariablen gehen vor."""
    datei = WURZEL / ".env"
    if not datei.exists():
        return
    for zeile in datei.read_text().splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        os.environ.setdefault(name.strip(), wert.strip().strip('"').strip("'"))


_env_datei()


def _e(name, standard=None):
    wert = os.environ.get(name)
    return wert if wert not in (None, "") else standard


STANDARD_MODELLE = {  # (Antwortmodell, Richtermodell)
    "openai": ("gpt-4.1-mini", "gpt-4.1"),
    "mistral": ("mistral-small-latest", "mistral-large-latest"),
    "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5"),
    "claude-cli": ("haiku", "sonnet"),
}
BASIS_URL = {"openai": "https://api.openai.com/v1", "mistral": "https://api.mistral.ai/v1",
             "anthropic": "https://api.anthropic.com/v1"}
SCHLUESSEL = {"openai": ("KOBENCH_API_KEY", "OPENAI_API_KEY"), "mistral": ("MISTRAL_API_KEY", "KOBENCH_API_KEY"),
              "anthropic": ("ANTHROPIC_API_KEY", "KOBENCH_API_KEY")}


def konfiguration(rolle="antwort"):
    """Anbieter, Modell, Basis-URL und Name der Schlüsselvariable für `antwort` oder `richter`."""
    anbieter = _e("KOBENCH_ANBIETER", "mistral")
    if rolle == "richter":
        anbieter = _e("KOBENCH_RICHTER_ANBIETER", anbieter)
    if anbieter not in STANDARD_MODELLE:
        raise ValueError(f"Unbekannter Anbieter {anbieter!r}; bekannt: {list(STANDARD_MODELLE)}")
    modell = (_e("KOBENCH_MODELL") if rolle == "antwort" else _e("KOBENCH_RICHTER")) \
        or STANDARD_MODELLE[anbieter][0 if rolle == "antwort" else 1]
    praefix = "KOBENCH_RICHTER_" if rolle == "richter" else "KOBENCH_"
    basis = _e(praefix + "BASE_URL") or (_e("KOBENCH_BASE_URL") if rolle == "richter" else None) \
        or BASIS_URL.get(anbieter)
    return {"anbieter": anbieter, "modell": modell, "basis": basis, "rolle": rolle}


def _schluessel(anbieter, rolle):
    namen = (("KOBENCH_RICHTER_API_KEY",) if rolle == "richter" else ()) + SCHLUESSEL.get(anbieter, ())
    for n in namen:
        if _e(n):
            return _e(n)
    if anbieter == "openai":  # lokale Server (Ollama, LM Studio) brauchen keinen Schlüssel
        return "ohne-schluessel"
    raise RuntimeError(f"Kein Schlüssel für {anbieter} gefunden (eine von {namen} setzen, siehe .env.example)")


ANTWORT_MODELL = konfiguration("antwort")["modell"]
RICHTER_MODELL = konfiguration("richter")["modell"]

_clients = {}


def _http(basis, kopf):
    schluessel = (basis, tuple(sorted(kopf.items())))
    if schluessel not in _clients:
        _clients[schluessel] = httpx.Client(base_url=basis, timeout=300, headers=kopf)
    return _clients[schluessel]


def _post(client, pfad, daten, versuche=8):
    warte = 2.0
    for n in range(versuche):
        try:
            r = client.post(pfad, json=daten)
        except httpx.TransportError:
            if n == versuche - 1:
                raise
            time.sleep(warte)
            warte *= 2
            continue
        if r.status_code in (429, 500, 502, 503, 504, 529) and n < versuche - 1:
            time.sleep(warte)
            warte = min(warte * 2, 60)
            continue
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------- OpenAI-kompatibel und Mistral

def _openai(nachrichten, k, werkzeuge, json_modus, max_tokens):
    client = _http(k["basis"], {"Authorization": f"Bearer {_schluessel(k['anbieter'], k['rolle'])}"})
    nachrichten = [{s: w for s, w in m.items() if not s.startswith("_")} for m in nachrichten]
    daten = {"model": k["modell"], "messages": nachrichten, "temperature": 0, "max_tokens": max_tokens}
    daten["random_seed" if k["anbieter"] == "mistral" else "seed"] = SEED
    if werkzeuge:
        daten["tools"] = werkzeuge
        daten["tool_choice"] = "auto"
    if json_modus:
        daten["response_format"] = {"type": "json_object"}
    antwort = _post(client, "/chat/completions", daten)
    msg = antwort["choices"][0]["message"]
    msg["content"] = msg.get("content") or ""
    return msg, antwort.get("usage", {})


# --------------------------------------------------------------------------- Anthropic Messages-API

def nach_anthropic(nachrichten, werkzeuge=None):
    """OpenAI-Nachrichten und -Werkzeuge in das Format der Messages-API übersetzen."""
    system = "\n\n".join(m["content"] for m in nachrichten if m["role"] == "system")
    aus = []
    for m in nachrichten:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if aus and aus[-1]["role"] == "user" and isinstance(aus[-1]["content"], list):
                aus[-1]["content"].append(block)
            else:
                aus.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant" and m.get("_roh"):
            aus.append({"role": "assistant", "content": m["_roh"]})  # unverändert, samt Denkblöcken
        elif m["role"] == "assistant" and m.get("tool_calls"):
            inhalt = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            inhalt += [{"type": "tool_use", "id": a["id"], "name": a["function"]["name"],
                        "input": json.loads(a["function"]["arguments"] or "{}")} for a in m["tool_calls"]]
            aus.append({"role": "assistant", "content": inhalt})
        else:
            aus.append({"role": m["role"], "content": m["content"]})
    tools = [{"name": w["function"]["name"], "description": w["function"]["description"],
              "input_schema": w["function"]["parameters"]} for w in werkzeuge or []]
    return system, aus, tools


def von_anthropic(antwort):
    """Antwort der Messages-API zurück ins OpenAI-Format (message, usage)."""
    text = "".join(b.get("text", "") for b in antwort.get("content", []) if b["type"] == "text")
    aufrufe = [{"id": b["id"], "type": "function",
                "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
               for b in antwort.get("content", []) if b["type"] == "tool_use"]
    msg = {"role": "assistant", "content": text}
    if aufrufe:
        msg["tool_calls"] = aufrufe
        msg["_roh"] = antwort["content"]  # für den nächsten Aufruf unverändert zurückgeben
    u = antwort.get("usage", {})
    return msg, {"prompt_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0),
                 "completion_tokens": u.get("output_tokens", 0)}


def _json_aus_text(text):
    text = text.strip()
    if text.startswith("{"):
        return text
    return text[text.find("{"):text.rfind("}") + 1] if "{" in text else text


def _anthropic(nachrichten, k, werkzeuge, json_modus, max_tokens):
    client = _http(k["basis"], {"x-api-key": _schluessel("anthropic", k["rolle"]),
                                "anthropic-version": "2023-06-01"})
    system, msgs, tools = nach_anthropic(nachrichten, werkzeuge)
    if json_modus:
        system += "\n\nAntworte ausschließlich mit einem gültigen JSON-Objekt, ohne Codeblock und ohne weiteren Text."
    # Keine temperature: Neuere Claude-Modelle lehnen Werte außer dem Standard ab.
    daten = {"model": k["modell"], "max_tokens": max(max_tokens, 4000), "system": system, "messages": msgs}
    if tools:
        daten["tools"] = tools
    msg, usage = von_anthropic(_post(client, "/messages", daten))
    if json_modus:
        msg["content"] = _json_aus_text(msg["content"])
    return msg, usage


# --------------------------------------------------------------------------- Claude-Code-CLI (Abo)

def _verlauf_als_text(nachrichten):
    teile = []
    for m in nachrichten:
        if m["role"] == "user":
            teile.append(f"### Nutzer\n{m['content']}")
        elif m["role"] == "assistant":
            aufrufe = [{"werkzeug": a["function"]["name"], "argumente": json.loads(a["function"]["arguments"] or "{}")}
                       for a in m.get("tool_calls") or []]
            teile.append(f"### Du\n{json.dumps({'aufrufe': aufrufe}, ensure_ascii=False) if aufrufe else m.get('content')}")
        elif m["role"] == "tool":
            teile.append(f"### Ergebnis Werkzeug {m.get('name')}\n{m['content']}")
    return "\n\n".join(teile)


def _claude_cli(nachrichten, k, werkzeuge, json_modus, max_tokens):
    """`claude -p` ohne Werkzeuge, Einstellungen, Hooks und MCP, in einem leeren Arbeitsverzeichnis.
    Werkzeugaufrufe werden als JSON im Text verabredet."""
    system = "\n\n".join(m["content"] for m in nachrichten if m["role"] == "system")
    if werkzeuge:
        system += ("\n\nDir stehen Werkzeuge zur Verfügung:\n"
                   + "\n".join(f"- {w['function']['name']}: {w['function']['description']} Argumente: "
                               f"{json.dumps(w['function']['parameters']['properties'], ensure_ascii=False)}"
                               for w in werkzeuge)
                   + '\nWillst du Werkzeuge aufrufen, antworte NUR mit JSON: {"aufrufe": [{"werkzeug": "...", '
                     '"argumente": {...}}]}. Willst du antworten, antworte mit dem Antworttext ohne JSON.')
    if json_modus:
        system += "\n\nAntworte ausschließlich mit einem gültigen JSON-Objekt, ohne Codeblock und ohne weiteren Text."
    befehl = ["claude", "-p", "--model", k["modell"], "--tools", "", "--strict-mcp-config", "--setting-sources", "",
              "--disable-slash-commands", "--no-session-persistence", "--output-format", "json",
              "--system-prompt", system]
    leer = Path(tempfile.gettempdir()) / "kobench-claude-leer"
    leer.mkdir(exist_ok=True)
    nicht_system = [m for m in nachrichten if m["role"] != "system"]
    for versuch in range(7):  # Drosselung im Abo: warten statt aufgeben
        p = subprocess.run(befehl, input=_verlauf_als_text(nicht_system), capture_output=True, text=True,
                           cwd=leer, timeout=900)
        try:
            d = json.loads(p.stdout)
            if not d.get("is_error"):
                break
        except json.JSONDecodeError:
            d = {}
        if versuch == 6:
            raise RuntimeError(f"claude -p fehlgeschlagen: {str(d.get('result') or p.stderr)[:200]}")
        time.sleep(min(30 * 2 ** versuch, 600))
    text = (d.get("result") or "").strip()
    u = d.get("usage", {})
    usage = {"prompt_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
             + u.get("cache_creation_input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}
    if json_modus:
        text = _json_aus_text(text)
    msg = {"role": "assistant", "content": text}
    if werkzeuge and text.lstrip().startswith("{") and '"aufrufe"' in text:
        try:
            aufrufe = json.loads(_json_aus_text(text))["aufrufe"]
            msg["tool_calls"] = [{"id": f"a{i}", "type": "function",
                                  "function": {"name": a["werkzeug"], "arguments": json.dumps(a.get("argumente", {}))}}
                                 for i, a in enumerate(aufrufe)]
            msg["content"] = ""
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return msg, usage


_WEGE = {"openai": _openai, "mistral": _openai, "anthropic": _anthropic, "claude-cli": _claude_cli}


def chat(nachrichten, modell=None, werkzeuge=None, json_modus=False, max_tokens=1500, rolle="antwort"):
    """Ein Chat-Aufruf. Gibt (message im OpenAI-Format, usage mit prompt_tokens/completion_tokens) zurück."""
    k = konfiguration(rolle)
    if modell:
        k["modell"] = modell
    return _WEGE[k["anbieter"]](nachrichten, k, werkzeuge, json_modus, max_tokens)


# --------------------------------------------------------------------------- Embeddings mit Plattencache

def embed_konfiguration():
    anbieter = _e("KOBENCH_EMBED_ANBIETER") or ("mistral" if _e("KOBENCH_ANBIETER", "mistral") == "mistral"
                                                else "openai")
    if anbieter not in ("openai", "mistral"):
        raise ValueError("KOBENCH_EMBED_ANBIETER muss openai (auch Ollama, LM Studio …) oder mistral sein")
    modell = _e("KOBENCH_EMBED_MODELL") or ("mistral-embed" if anbieter == "mistral" else "text-embedding-3-small")
    basis = _e("KOBENCH_EMBED_BASE_URL") or (BASIS_URL["mistral"] if anbieter == "mistral"
                                             else _e("KOBENCH_BASE_URL") or BASIS_URL["openai"])
    return {"anbieter": anbieter, "modell": modell, "basis": basis}


_EMBED = {}  # modell -> {sha256: Vektor}
_EMBED_SPERRE = threading.Lock()


def _embed_cache(modell):
    if modell not in _EMBED:
        cache = {}
        datei = CACHE / f"embed-{modell.replace('/', '_')}.jsonl"
        if datei.exists():
            for zeile in datei.read_text().splitlines():
                e = json.loads(zeile)
                cache[e["h"]] = np.frombuffer(base64.b64decode(e["b"]), dtype=np.float32)
        _EMBED[modell] = cache
    return _EMBED[modell]


def _embed_stueck(k, stueck, fh):
    """Ein Embedding-Aufruf; zu große Stapel werden halbiert."""
    schl = _e("KOBENCH_EMBED_API_KEY") or _schluessel(k["anbieter"], "antwort")
    client = _http(k["basis"], {"Authorization": f"Bearer {schl}"})
    try:
        erg = _post(client, "/embeddings", {"model": k["modell"], "input": [t[:8000] for _, t in stueck]})
    except httpx.HTTPStatusError as fehler:
        if fehler.response.status_code == 400 and len(stueck) > 1:
            mitte = len(stueck) // 2
            _embed_stueck(k, stueck[:mitte], fh)
            _embed_stueck(k, stueck[mitte:], fh)
            return
        raise
    cache = _EMBED[k["modell"]]
    for (h, _), d in zip(stueck, erg["data"]):
        v = np.asarray(d["embedding"], dtype=np.float32)
        cache[h] = v
        fh.write(json.dumps({"h": h, "b": base64.b64encode(v.tobytes()).decode()}) + "\n")
    fh.flush()


def embed(texte, stapel=64, max_zeichen=60000):
    """Normierte Embeddings; zeilenweise auf Platte gecacht (Schlüssel = sha256 des Textes)."""
    k = embed_konfiguration()
    CACHE.mkdir(exist_ok=True)
    hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texte]
    with _EMBED_SPERRE:
        vorhanden = _embed_cache(k["modell"])
        fehlend = list({h: t for h, t in zip(hashes, texte) if h not in vorhanden}.items())
        if fehlend:
            with (CACHE / f"embed-{k['modell'].replace('/', '_')}.jsonl").open("a") as fh:
                stueck, groesse = [], 0
                for h, t in fehlend:
                    if stueck and (len(stueck) >= stapel or groesse + min(len(t), 8000) > max_zeichen):
                        _embed_stueck(k, stueck, fh)
                        stueck, groesse = [], 0
                    stueck.append((h, t))
                    groesse += min(len(t), 8000)
                if stueck:
                    _embed_stueck(k, stueck, fh)
        m = np.array([vorhanden[h] for h in hashes], dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)
