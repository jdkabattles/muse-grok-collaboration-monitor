#!/usr/bin/env python3
"""Reviewed read-only validation subset, NOT imported from fetched source.
Derived from muse-bot-collab ff14560830b17b959ae9eab74afb1a5f93a86490,
mailbox/messenger.py; see LIVE.md. No ACK, message creation or handler code.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re

MAX_BYTES = 65536
MAX_FILES = 1000
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
# Configured agent IDs need not be v4; message IDs and nonces MUST be v4.
AGENT = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
HEX = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REF = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
ORIGINS = {"t81u", "t95u"}
LABELS = {"local-observed", "source-reported", "user-attested", "unverified"}
TRANSITIONS = {None:{"received"}, "received":{"validated","rejected","failed"},
               "validated":{"accepted","rejected","failed"},
               "accepted":{"completed","failed"}, "completed":set(), "failed":set(), "rejected":set()}

# ONE reviewed historical exception. This is not a general terminal-reopen API.
LEGACY_MESSAGE_ID="29446e63-76ff-472b-a90e-96e9ef6d05db"
LEGACY_MESSAGE_SHA="ac533e91721dfbae380751f16294a7c5133c2a6511b7fda50a7d2d771aa2a594"
LEGACY_EVENT_ID="f196585e-ca04-444a-becb-6a17f83753ea"
LEGACY_EVENT_SHA="897f77ded452a4137adcc74488b63da2611a35ecddb0cf08cd44c2c95e63c5c2"
LEGACY_FILE_SHA="71bfeece2b5aaff3611bc09bbd76740623d2aa3cd7967c89402acee6e1f40c4c"
LEGACY_ACTOR="d10e442c-22cc-46e7-a879-479372fb9fbf"
REVOCATION="I revoke the legacy completion assertion; this event does not assert task completion."
BASE_EVENT_FIELDS="version id message_id message_sha256 actor timestamp status sequence previous_sha256 source_commit note sha256"

def legacy_path():
    return Path("events")/LEGACY_MESSAGE_ID/("4-"+LEGACY_EVENT_ID+".json")

def event_path(event):
    return Path("events")/event["message_id"]/(str(event["sequence"])+"-"+event["id"]+".json")

def is_legacy(event):
    return (event.get("id")==LEGACY_EVENT_ID and event.get("sha256")==LEGACY_EVENT_SHA
            and event.get("message_id")==LEGACY_MESSAGE_ID and event.get("message_sha256")==LEGACY_MESSAGE_SHA
            and event.get("actor")==LEGACY_ACTOR and event.get("status")=="completed" and event.get("sequence")==4)

def validate_revocation(event, previous):
    require(previous and is_legacy(previous),"revocation only for exact allowlisted legacy event")
    require(event["message_id"]==LEGACY_MESSAGE_ID and event["message_sha256"]==LEGACY_MESSAGE_SHA
            and event["actor"]==LEGACY_ACTOR and event["sequence"]==5
            and event["revokes_event_id"]==LEGACY_EVENT_ID and event["revokes_event_sha256"]==LEGACY_EVENT_SHA
            and event["revocation_statement"]==REVOCATION,"revocation target/statement mismatch")

def allowed_transition(previous, event):
    if event["status"]=="completion-revoked":
        validate_revocation(event,previous)
        return True
    if previous and previous["status"]=="completion-revoked":
        return event["status"] in {"completed","failed"} and event["sequence"]==6
    return event["status"] in TRANSITIONS.get(previous["status"] if previous else None,set())

class Invalid(ValueError):
    pass

def require(ok, text):
    if not ok:
        raise Invalid(text)

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=True, allow_nan=False).encode("ascii")

def digest(obj):
    return hashlib.sha256(canonical({k:v for k,v in obj.items() if k != "sha256"})).hexdigest()

def seal(obj):
    return dict(obj, sha256=digest(obj))

def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def time(value):
    require(isinstance(value,str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",value), "invalid UTC timestamp")
    try:
        return dt.datetime.strptime(value,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as e:
        raise Invalid("invalid calendar time") from e

def keys(obj, expected):
    require(isinstance(obj,dict) and set(obj)==set(expected.split()), "unexpected/missing fields")

def text(value, limit):
    require(isinstance(value,str) and 0 < len(value) <= limit and not any(ord(c)<32 and c not in "\n\t" for c in value), "invalid text")

def no_symlinks(path):
    for part in [path,*path.parents]:
        require(not part.is_symlink(), "symlink refused")

def load(path):
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "missing/oversized file")
    def unique(pairs):
        out={}
        for k,v in pairs:
            require(k not in out,"duplicate JSON key")
            out[k]=v
        return out
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as e:
        raise Invalid("invalid JSON") from e

def agent(value, agents):
    require(isinstance(value,str) and AGENT.fullmatch(value) and value in agents,"unknown/invalid agent")

def registry(root):
    data=load(root/"agents.json")
    keys(data,"version agents pending")
    require(type(data["version"]) is int and data["version"]==1 and isinstance(data["agents"],dict) and data["agents"],"invalid registry")
    for a, info in data["agents"].items():
        require(AGENT.fullmatch(a),"invalid configured agent")
        keys(info,"name kind")
        text(info["name"],80)
        require(info["kind"] in {"grok","muse"},"invalid agent kind")
    require(isinstance(data["pending"],list) and all(isinstance(x,str) for x in data["pending"]),"invalid pending list")
    return data["agents"]

def validate_message(m, agents, now=None):
    keys(m,"version id from to timestamp expires_at nonce type thread_id in_reply_to payload status sha256")
    require(type(m["version"]) is int and m["version"]==1,"unsupported version")
    for k in ("id","nonce","thread_id"):
        require(isinstance(m[k],str) and UUID.fullmatch(m[k]),"invalid ID/nonce")
    agent(m["from"],agents); agent(m["to"],agents)
    require(m["from"]!=m["to"],"self-message refused")
    require(m["type"] in {"request","response"} and m["status"]=="queued","invalid type/immutable status")
    if m["type"]=="request":
        require(m["thread_id"]==m["id"] and m["in_reply_to"] is None,"request threading")
    else:
        require(isinstance(m["in_reply_to"],str) and UUID.fullmatch(m["in_reply_to"]),"response parent")
    t=time(m["timestamp"]); end=time(m["expires_at"])
    now=now or dt.datetime.now(dt.timezone.utc)
    require(dt.timedelta(0)<end-t<=dt.timedelta(days=7),"expiry bounds")
    require(t<=now+dt.timedelta(minutes=5),"future message")
    # Expiry gates fresh receipt/acceptance, not tracking already-received work.
    p=m["payload"]
    keys(p,"action subject text scope origin evidence")
    require(p["action"] == "handoff-"+m["type"],"executable/unknown/mismatched action refused")
    require(p["scope"]=="local-review-only" and p["origin"] in ORIGINS,"authority scope refused")
    text(p["subject"],160); text(p["text"],8000)
    require(isinstance(p["evidence"],list) and len(p["evidence"])<=16,"evidence bounds")
    references=set()
    for e in p["evidence"]:
        keys(e,"label reference sha256")
        require(e["label"] in LABELS,"evidence label")
        ref=e["reference"]
        require(isinstance(ref,str) and len(ref)<=240 and REF.fullmatch(ref) and all(x not in {".",".."} for x in ref.split("/")),"unsafe reference")
        require(ref not in references,"duplicate evidence reference")
        references.add(ref)
        require(isinstance(e["sha256"],str) and HEX.fullmatch(e["sha256"]),"evidence digest")
    require(isinstance(m["sha256"],str) and HEX.fullmatch(m["sha256"]) and digest(m)==m["sha256"],"message digest mismatch")
    return end > now

def files(base):
    no_symlinks(base)
    require(base.is_dir(),"missing mailbox folder")
    found=[]
    def walk_error(error):
        raise Invalid("unreadable mailbox subtree") from error
    entries=0
    for folder, dirs, names in os.walk(base,followlinks=False,onerror=walk_error):
        entries += len(dirs)+len(names)
        require(entries<=MAX_FILES*3,"tree entry limit exceeded")
        for name in dirs+names:
            path=Path(folder)/name
            require(not path.is_symlink(),"symlink refused")
        for name in names:
            path=Path(folder)/name
            if path == base/".gitkeep" and path.stat().st_size == 0:
                continue
            require(path.suffix==".json","unexpected file in message/event tree")
            found.append(path)
            require(len(found)<=MAX_FILES,"file limit exceeded")
    return sorted(found)

def scan(root, now=None, extra_event=None, extra_message=None):
    agents=registry(root); messages={}; nonces=set()
    message_records=[(path,load(path)) for path in files(root/"inbox")]
    if extra_message is not None:
        message_records.append((root/"inbox"/extra_message["to"]/(extra_message["id"]+".json"),extra_message))
    require(len(message_records)<=MAX_FILES,"message file limit exceeded")
    for path,m in message_records:
        validate_message(m,agents,now)
        require(path.relative_to(root/"inbox").parts==(m["to"],m["id"]+".json"),"wrong recipient/path")
        require(m["id"] not in messages,"duplicate message ID: quarantine entire batch")
        require(m["nonce"] not in nonces,"duplicate nonce")
        messages[m["id"]]=m; nonces.add(m["nonce"])
    for m in messages.values():
        if m["type"]=="response":
            parent=messages.get(m["in_reply_to"])
            require(parent and parent["type"]=="request" and parent["thread_id"]==m["thread_id"] and parent["to"]==m["from"] and parent["from"]==m["to"] and time(m["timestamp"])>=time(parent["timestamp"]),"unbound response")
    chains={}
    records=[(path,load(path)) for path in files(root/"events")]
    if extra_event is not None:
        require(extra_event.get("status")=="completion-revoked","only revocation may be staged in memory")
        records.append((root/event_path(extra_event),extra_event))
    require(len(records)<=MAX_FILES,"event file limit exceeded")
    for path,e in records:
        require(isinstance(e,dict),"invalid event object")
        require(e.get("id")!=LEGACY_EVENT_ID or is_legacy(e),"reserved legacy event cannot be replaced/resealed")
        extra=(" revokes_event_id revokes_event_sha256 revocation_statement" if e.get("status")=="completion-revoked"
               else " completion_response_id completion_response_sha256" if e.get("status")=="completed" and not is_legacy(e) else "")
        keys(e,BASE_EVENT_FIELDS+extra)
        if is_legacy(e):
            require(hashlib.sha256(path.read_bytes()).hexdigest()==LEGACY_FILE_SHA,"legacy immutable bytes changed")
        require(type(e["version"]) is int and e["version"]==1,"event version")
        require(isinstance(e["id"],str) and UUID.fullmatch(e["id"]),"event ID")
        require(isinstance(e["message_id"],str) and e["message_id"] in messages,"orphan event")
        m=messages[e["message_id"]]
        require(e["actor"]==m["to"] and e["message_sha256"]==m["sha256"],"event recipient/digest mismatch")
        require(type(e["sequence"]) is int and 1<=e["sequence"]<=(6 if e["message_id"]==LEGACY_MESSAGE_ID else 4),"event sequence")
        require(path.relative_to(root/"events").parts==(m["id"],str(e["sequence"])+"-"+e["id"]+".json"),"event path")
        require(isinstance(e["source_commit"],str) and COMMIT.fullmatch(e["source_commit"]),"source commit required")
        require(time(e["timestamp"])>=time(m["timestamp"]) and time(e["timestamp"])<= (now or dt.datetime.now(dt.timezone.utc))+dt.timedelta(minutes=5),"event time")
        text(e["note"],1000)
        require(isinstance(e["sha256"],str) and HEX.fullmatch(e["sha256"]) and digest(e)==e["sha256"],"event digest mismatch")
        chains.setdefault(m["id"],[]).append(e)
    event_ids=set()
    for mid, chain in chains.items():
        chain.sort(key=lambda e:e["sequence"])
        prev=None
        for seq,e in enumerate(chain,1):
            require(e["id"] not in event_ids,"duplicate event ID")
            event_ids.add(e["id"])
            require(e["sequence"]==seq and e["previous_sha256"]==(prev["sha256"] if prev else None),"event fork/gap")
            require(allowed_transition(prev,e),"invalid status transition")
            validate_progress(messages[mid], e["status"], time(e["timestamp"]), prev)
            require(not prev or time(e["timestamp"])>=time(prev["timestamp"]),"event clock reversal")
            prev=e
        if mid==LEGACY_MESSAGE_ID and len(chain)>=4:
            require(is_legacy(chain[3]),"known original completion cannot be replaced")
        legacy=[e for e in chain if is_legacy(e)]
        if legacy:
            require(len(chain)>=5 and chain[4]["status"]=="completion-revoked",
                    "legacy completion remains quarantined until exact recipient revocation")
    validate_links(messages,chains)
    return messages,chains

def validate_progress(message, status, when, previous):
    expired=when >= time(message["expires_at"])
    # Receipt must precede expiry; late validation records review only, not authority.
    require(not (expired and status in {"received","accepted"}),"expired: no fresh receipt/acceptance")
    if message["type"]=="response":
        require(status in {"received","validated","rejected","failed"},"responses are evidence-only, not new tasks")
        require(not previous or previous["status"]!="validated","response review is terminal")

def completion_response(message, event, messages, chains):
    require(message["type"]=="request","only requests can complete")
    rid=event.get("completion_response_id")
    require(isinstance(rid,str) and UUID.fullmatch(rid),"completion needs response ID")
    response=messages.get(rid)
    require(response and response["type"]=="response" and response["in_reply_to"]==message["id"]
            and response["thread_id"]==message["thread_id"] and response["from"]==message["to"]
            and response["to"]==message["from"],"completion response threading/recipient")
    require(event.get("completion_response_sha256")==response["sha256"],"completion response digest")
    accepted=next((e for e in chains.get(message["id"],[]) if e["status"]=="accepted"),None)
    require(accepted and time(accepted["timestamp"])<=time(response["timestamp"])<=time(event["timestamp"]),
            "completion response must follow acceptance and precede completion")
    require(any(e["label"]=="local-observed" for e in response["payload"]["evidence"]),
            "completion needs SHA-pinned locally observed artifact evidence")
    observed={e["reference"] for e in response["payload"]["evidence"] if e["label"]=="local-observed"}
    require({e["reference"] for e in message["payload"]["evidence"]} <= observed,
            "completion response omits requested artifact references")
    return response

def validate_links(messages, chains):
    for message in messages.values():
        if message["type"]=="response":
            parent=messages[message["in_reply_to"]]
            # Grace is reporting only: one week after request expiry, never new work.
            if time(message["timestamp"])>=time(parent["expires_at"]):
                accepted=next((e for e in chains.get(parent["id"],[]) if e["status"]=="accepted"),None)
                require(accepted and time(accepted["timestamp"])<time(parent["expires_at"]),
                        "late response needs pre-expiry accepted work")
                require(time(message["timestamp"])<=time(parent["expires_at"])+dt.timedelta(days=7),
                        "late response outside seven-day reporting grace")
                terminal=next((e for e in chains.get(parent["id"],[]) if e["status"] in {"completed","failed","rejected"} and not is_legacy(e)),None)
                require(not terminal or time(message["timestamp"])<=time(terminal["timestamp"]),
                        "late response after terminal closure")
    for mid, chain in chains.items():
        for event in chain:
            if event["status"]=="completed" and not is_legacy(event):
                completion_response(messages[mid],event,messages,chains)
