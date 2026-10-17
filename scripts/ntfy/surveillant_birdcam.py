#!/usr/bin/env python3
"""Watcher for the birdcam, run on macaron (always on) every minute by launchd.

If the birdcam Pi, the network or the gallery goes down nobody notices: this watcher, outside the Pi, tells FX through ntfy.
It makes one read-only request on a static page of the gallery (GET <gallery>/static/mesange.svg, no work on the Pi side).
An HTTP 200 proves that the Pi is on, reachable and that birdcam-gallery serves its static files. It does not prove that
the capture (birdcam.service) runs, nor that the photo directory is readable: neither is watched (see ALARME_NTFY.md).

Sends a ntfy message after CONFIRMATIONS failed minutes in a row, a reminder every REMINDER_S, and a recovery message
after RECOVERY successful minutes. To protect the shared ntfy.sh quota (250 messages a day per IP, also used by the spirubot
alarms), an outage that comes back less than HOLD_S after a recovery is not announced again at once, and a flapping gallery
makes at most about 100 messages a day. A failed send is retried with a growing wait (1, 2, 4, ... 30 minutes);
a recovery message that may have been delivered never hides a new outage. The ntfy
topic is not the one of spirubot.

Configuration: ~/.config/birdcam/veilleur.json (mode 0600):
  {"gallery": "http://192.168.1.40:5000", "url": "https://ntfy.sh", "topic": "birdcam-xxxxxxxxxxxxxxxx"}
State between two runs: ~/.local/state/birdcam/veilleur.json. Standard Python 3, no dependency.
Tests: python3 scripts/test_surveillant_birdcam.py
"""

import json
import math
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlparse

CONFIG = os.path.expanduser('~/.config/birdcam/veilleur.json')
STATE = os.path.expanduser('~/.local/state/birdcam/veilleur.json')
TIMEOUT_S = 6
CONFIRMATIONS = 5          # failed minutes in a row before the alarm
RECOVERY = 2               # successful minutes in a row before the recovery message
REMINDER_S = 6 * 3600
HOLD_S = 30 * 60           # an outage back less than this after a recovery is declared but announced only when it lasts
RETRY_MAX_S = 30 * 60      # longest wait after a failed send
GAP_S = 180                # longer than this between two runs (macaron off, asleep): the counted minutes are forgotten
PROBE = '/static/mesange.svg'
LABEL = 'Birdcam injoignable (Pi éteint, réseau ou service de la galerie arrêté)'
TOPIC_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')
EMPTY = {'fails': 0, 'oks': 0, 'in_alarm': 0, 'announced': 0, 'recovery_pending': 0, 'last_sent': None, 'recovered_at': None,
         'retry_at': None, 'send_failures': 0, 'seen': None}
MESSAGE_KEYS = ('in_alarm', 'announced', 'recovery_pending', 'last_sent', 'recovered_at', 'retry_at', 'send_failures')


def probe(gallery, urlopen=urllib.request.urlopen):
    """True if the gallery answers HTTP 200 on the static page."""
    try:
        with urlopen(gallery + PROBE, timeout=TIMEOUT_S) as r:
            r.read(4096)
            return r.status == 200
    except Exception:
        return False


def clean_state(raw):
    """State read from disk with the right types, or the empty state if anything is off."""
    if not isinstance(raw, dict):
        return dict(EMPTY)
    state = dict(EMPTY)
    for key in ('fails', 'oks', 'in_alarm', 'announced', 'recovery_pending', 'send_failures'):
        v = raw.get(key, 0)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return dict(EMPTY)
        state[key] = v
    for key in ('last_sent', 'recovered_at', 'retry_at', 'seen'):
        v = raw.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
            return dict(EMPTY)
        state[key] = v
    return state


def advance(reachable, state, now):
    """(new state, 'alarm' | 'reminder' | 'recovered' | None). Pure function. The new state already records the message as
    sent; `revert_message` undoes that if the send fails. `in_alarm` is the outage, `announced` tells whether FX was told."""
    s = dict(state)
    sent = None
    if not reachable:
        s['fails'], s['oks'] = s['fails'] + 1, 0
        if s['recovery_pending'] and s['fails'] >= CONFIRMATIONS:
            # a recovery message that may have been delivered, then the Pi is down again: this is a new outage to announce
            s['in_alarm'], s['announced'], s['recovery_pending'], s['recovered_at'] = 1, 0, 0, None
        if not s['in_alarm'] and s['fails'] >= CONFIRMATIONS:
            s['in_alarm'], s['announced'] = 1, 0
        if s['in_alarm'] and not s['announced']:
            held = s['recovered_at'] is not None and 0 <= now - s['recovered_at'] < HOLD_S
            if not held:
                s['announced'], s['last_sent'], sent = 1, now, 'alarm'
        elif s['in_alarm'] and s['last_sent'] is not None and now - s['last_sent'] >= REMINDER_S:
            s['last_sent'], sent = now, 'reminder'
    else:
        s['oks'], s['fails'] = s['oks'] + 1, 0
        if s['in_alarm'] and s['oks'] >= RECOVERY:
            if s['announced']:
                s['recovered_at'], sent = now, 'recovered'
            s['recovery_pending'] = 0
            s['in_alarm'], s['announced'] = 0, 0          # an outage never announced ends in silence; the hold window stays put
    return s, sent


def revert_message(new, previous):
    """`new` with the message fields of `previous`: the counters move on, the message is considered unsent."""
    s = dict(new)
    for key in MESSAGE_KEYS:
        s[key] = previous[key]
    return s


def retry_after_failure(state, now):
    """`state` (message not sent) with a growing wait before the next try."""
    s = dict(state)
    s['send_failures'] = state.get('send_failures', 0) + 1
    s['retry_at'] = now + min(RETRY_MAX_S, 60 * 2 ** (s['send_failures'] - 1))
    return s


def load_config(path=CONFIG):
    try:
        with open(path) as f:
            c = json.load(f)
        gallery, url, topic, token = c['gallery'], c['url'], c['topic'], c.get('token')
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for u in (gallery, url):
        p = urlparse(u) if isinstance(u, str) else None
        if p is None or p.scheme not in ('http', 'https') or not p.netloc:
            return None
    if not isinstance(topic, str) or not TOPIC_RE.fullmatch(topic):
        return None
    if token is not None and (not isinstance(token, str) or not re.fullmatch(r'[\x21-\x7e]{1,200}', token)):
        return None
    return {'gallery': gallery.rstrip('/'), 'url': url.rstrip('/'), 'topic': topic, 'token': token}


def publish(cfg, title, text, priority, urlopen=urllib.request.urlopen):
    body = json.dumps({'topic': cfg['topic'], 'title': title, 'message': text, 'priority': priority}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if cfg.get('token'):
        headers['Authorization'] = 'Bearer ' + cfg['token']
    try:
        with urlopen(urllib.request.Request(cfg['url'], data=body, headers=headers, method='POST'), timeout=TIMEOUT_S) as r:
            r.read(1024)
            return 200 <= r.status < 300
    except Exception:
        return False


def read_state(path=STATE):
    try:
        with open(path) as f:
            return clean_state(json.load(f))
    except (OSError, ValueError):
        return dict(EMPTY)


def write_state(state, path=STATE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run_once(cfg, urlopen=urllib.request.urlopen, now=None, state_path=STATE):
    """One watch. The state is written BEFORE the send: if it cannot be written (full disk), nothing is sent rather than
    resending every minute. Returns the type of message sent, or None."""
    now = time.time() if now is None else now
    previous = read_state(state_path)
    if previous['seen'] is not None and not 0 <= now - previous['seen'] <= GAP_S:
        previous['fails'] = previous['oks'] = 0                 # macaron was off, or the clock moved: forget the counted minutes
    if previous['retry_at'] is not None and previous['retry_at'] > now + RETRY_MAX_S:
        previous['retry_at'] = None                             # a wait longer than the longest possible one: clock error
    new, kind = advance(probe(cfg['gallery'], urlopen), previous, now)
    if kind and previous['retry_at'] is not None and now < previous['retry_at']:
        new = revert_message(new, previous)                     # waiting after a failed send: this minute only counts
        kind = None
    if kind or (not new['in_alarm'] and not new['recovery_pending'] and new['fails'] < CONFIRMATIONS):
        new['send_failures'], new['retry_at'] = 0, None         # nothing pending any more: forget the old send failures
    new['seen'] = now
    write_state(new, state_path)                                # raises OSError: nothing is sent, the error reaches the log
    if not kind:
        return None
    if kind == 'recovered':
        title, text, priority = '[Rétabli] ' + LABEL, 'Retour à la normale.', 3
    else:
        title = '[Birdcam] ' + LABEL
        text = LABEL + ('. Rappel.' if kind == 'reminder' else '.')
        priority = 4
    if publish(cfg, title, text, priority, urlopen):
        return kind
    print('veilleur birdcam : envoi impossible, repris plus tard', file=sys.stderr, flush=True)
    # the minute counted all the same: the counters move on, so that the message is retried when the wait ends
    failed = revert_message(new, previous)
    if kind == 'recovered':
        failed['recovery_pending'] = 1                          # the request may have reached ntfy: see advance()
    try:
        write_state(retry_after_failure(failed, now), state_path)
    except OSError as exc:
        print('veilleur birdcam : état non enregistré après un envoi raté (%s)' % exc, file=sys.stderr, flush=True)
    return None


def main():
    cfg = load_config()
    if cfg is None:
        print('veilleur birdcam : configuration absente ou invalide (%s)' % CONFIG, file=sys.stderr)
        return 2
    run_once(cfg)
    return 0


if __name__ == '__main__':
    sys.exit(main())
