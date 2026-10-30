import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";

// Same palette as the board page (dark theme).
const C = {
  bg: "#1b1a18", card: "#252421", text: "#ecebe8", muted: "#a29f98", line: "#36342f", bar: "#34322d",
  accent: "#e0805e", ok: "#5cbf83", warn: "#e0a84a", stop: "#ef6b5b",
};
const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif';
const MONO = '"SF Mono", Menlo, monospace';
const ease = Easing.inOut(Easing.cubic);

// Value at frame f along [frame, value] keyframes, eased and clamped.
const track = (f: number, keys: [number, number][]) =>
  interpolate(f, keys.map((k) => k[0]), keys.map((k) => k[1]), {
    easing: ease, extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
const fade = (f: number, a: number, b: number, c?: number, d?: number) =>
  track(f, c === undefined || d === undefined ? [[a, 0], [b, 1]] : [[a, 0], [b, 1], [c, 1], [d, 0]]);

const CARD_Y = 92, CARD_H = 352, CHIP_W = 256;
const A_X = 24, B_X = 337, F_X = 650;
const SLOT_Y = CARD_Y + 250;
const QX = B_X + 15, q = (i: number) => 150 + i * 54;
const DONE_Y = 392;

const barColor = (v: number, stop: number) => (v >= stop ? C.stop : v >= stop - 15 ? C.warn : C.ok);

const Bar: React.FC<{ label: string; value: number; stop: number }> = ({ label, value, stop }) => (
  <div style={{ marginTop: 14 }}>
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, color: C.text }}>
      <span>{label}</span><span>{Math.round(value)}%</span>
    </div>
    <div style={{ position: "relative", height: 8, background: C.bar, borderRadius: 8, marginTop: 5, overflow: "hidden" }}>
      <div style={{ width: `${value}%`, height: "100%", background: barColor(value, stop), borderRadius: 8 }} />
      <div style={{ position: "absolute", left: `${stop}%`, top: 0, bottom: 0, width: 2, background: C.text, opacity: 0.4 }} />
    </div>
  </div>
);

const Pill: React.FC<{ text: string; color: string }> = ({ text, color }) => (
  <span style={{ fontSize: 12, color, border: `1px solid ${color}`, borderRadius: 99, padding: "2px 9px" }}>{text}</span>
);

const Card: React.FC<{ x: number; name: string; pill: [string, string]; fiveH: number; ctx: number; opacity: number }> =
  ({ x, name, pill, fiveH, ctx, opacity }) => (
    <div style={{ position: "absolute", left: x, top: CARD_Y, width: 286, height: CARD_H, background: C.card,
                  border: `1px solid ${C.line}`, borderRadius: 14, padding: "16px 15px", boxSizing: "border-box", opacity }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <b style={{ fontSize: 18, letterSpacing: 0.5 }}>{name}</b><Pill text={pill[0]} color={pill[1]} />
      </div>
      <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>Claude Code session</div>
      <Bar label="5-hour limit" value={fiveH} stop={85} />
      <Bar label="Context window" value={ctx} stop={70} />
      <div style={{ position: "absolute", top: 218, left: 15, fontSize: 12, color: C.muted, textTransform: "uppercase", letterSpacing: 1 }}>
        Working on
      </div>
    </div>
  );

const Chip: React.FC<{ id: number; title: string; x: number; y: number; done?: boolean; note?: number; opacity: number }> =
  ({ id, title, x, y, done, note = 0, opacity }) => (
    <div style={{ position: "absolute", left: x, top: y, width: CHIP_W, opacity, background: "#2d2b28",
                  border: `1px solid ${done ? C.ok : C.line}`, borderRadius: 10, padding: "11px 12px", boxSizing: "border-box",
                  fontSize: 14, boxShadow: "0 4px 14px rgba(0,0,0,.35)" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span><span style={{ color: C.muted }}>#{id}</span> {title}</span>
        {done ? <span style={{ color: C.ok }}>✓</span> : null}
      </div>
      {note > 0 ? (
        <div style={{ fontSize: 12, color: C.warn, marginTop: 6, opacity: note, height: 16 * note, overflow: "hidden" }}>
          📝 handover: form wired, 2 tests left
        </div>
      ) : null}
    </div>
  );

const CAPTIONS: [number, number, string][] = [
  [85, 175, "Each session claims its own task from the shared board"],
  [175, 300, "Every account works in parallel, never on the same task"],
  [300, 425, "Account 1 hits its 5-hour limit and hands its task over, with notes"],
  [425, 505, "Account 2's context reaches 70%: it saves a summary to the board"],
  [505, 625, "A fresh session resumes from two lines. No compaction."],
];

const PROMPT = [
  'Run: curl -sS "$COSHIFT_URL/api/help" -H "Authorization: Bearer $COSHIFT_TOKEN" and follow it.',
  "Start with board resume and continue from your saved context.",
];

export const Coshift: React.FC = () => {
  const f = useCurrentFrame();
  const scene = fade(f, 62, 85, 625, 640);
  const board = fade(f, 70, 100);

  // chip paths: [frame, x] and [frame, y]
  const one = {
    x: track(f, [[110, QX], [145, A_X + 15], [330, A_X + 15], [370, QX], [385, QX], [420, F_X + 15]]),
    y: track(f, [[110, q(0)], [145, SLOT_Y], [330, SLOT_Y], [370, q(2)], [385, q(2)], [420, SLOT_Y]]),
  };
  const two = {
    x: track(f, [[130, QX], [165, F_X + 15], [330, F_X + 15], [365, QX]]),
    y: track(f, [[130, q(1)], [165, SLOT_Y], [330, SLOT_Y], [365, DONE_Y]]),
  };
  const three = track(f, [[170, q(2)], [200, q(0)]]);
  const four = track(f, [[170, q(3)], [200, q(1)]]);

  const aFive = track(f, [[170, 38], [300, 87]]);
  const aCtx = track(f, [[170, 22], [300, 34]]);
  const fFive = track(f, [[170, 12], [470, 31]]);
  const fCtx = track(f, [[170, 30], [400, 48], [465, 72], [596, 72], [616, 6]]);

  const aPill: [string, string] = f < 300 ? ["Working", C.ok] : ["Stopped · limit", C.stop];
  const fPill: [string, string] = f < 465 ? ["Working", C.ok] : f < 600 ? ["Saving context", C.warn] : ["Resumed ✓", C.ok];

  const doc = { t: track(f, [[470, 0], [500, 1]]), o: fade(f, 468, 474, 494, 502) };
  const prompt = fade(f, 505, 520, 590, 605);
  const typed = Math.floor(track(f, [[520, 0], [578, PROMPT[0].length + PROMPT[1].length]]));
  const title = fade(f, 0, 12, 55, 70);
  const end = fade(f, 628, 645);

  return (
    <AbsoluteFill style={{ background: C.bg, color: C.text, fontFamily: FONT }}>
      {/* title */}
      <AbsoluteFill style={{ opacity: title, justifyContent: "center", alignItems: "center" }}>
        <div style={{ width: 120, height: 18, borderRadius: 9, background: C.accent,
                      transform: `rotate(${track(f, [[0, -25], [45, 0]])}deg)`, marginBottom: 28 }} />
        <div style={{ fontSize: 76, fontWeight: 800, letterSpacing: -1 }}>Coshift</div>
        <div style={{ fontSize: 22, color: C.muted, marginTop: 10 }}>Your Claude Code accounts hand work to each other</div>
      </AbsoluteFill>

      <AbsoluteFill style={{ opacity: scene }}>
        <div style={{ position: "absolute", left: 24, top: 30, fontSize: 22, fontWeight: 700 }}>
          Coshift <span style={{ color: C.muted, fontWeight: 400, fontSize: 15 }}>(team board) · any number of accounts, one project</span>
        </div>

        <Card x={A_X} name="Account 1" pill={aPill} fiveH={aFive} ctx={aCtx} opacity={1} />
        <Card x={F_X} name="Account 2" pill={fPill} fiveH={fFive} ctx={fCtx} opacity={1} />

        {/* board */}
        <div style={{ position: "absolute", left: B_X, top: CARD_Y, width: 286, height: CARD_H, opacity: board,
                      border: `1px dashed ${C.accent}`, borderRadius: 14, padding: "14px 15px", boxSizing: "border-box",
                      background: "rgba(224,128,94,.05)" }}>
          <b style={{ fontSize: 16 }}>Shared board</b>
          <div style={{ fontSize: 12, color: f > 500 ? C.warn : C.muted, marginTop: 3, height: 16 }}>
            {f > 500 ? "📄 Account 2 saved its context · just now" : "Queue"}
          </div>
          <div style={{ position: "absolute", top: DONE_Y - CARD_Y - 22, left: 15, fontSize: 12, color: C.muted,
                        textTransform: "uppercase", letterSpacing: 1 }}>Done</div>
        </div>

        <Chip id={3} title="Emails: shipped" x={QX} y={three} opacity={board} />
        <Chip id={4} title="Fix flaky cart test" x={QX} y={four} opacity={board} />
        <Chip id={2} title="Orders: pagination" x={two.x} y={two.y} done={f >= 300} opacity={board} />
        <Chip id={1} title="Checkout: validation" x={one.x} y={one.y} note={fade(f, 318, 335)} opacity={board} />

        {/* context summary flying to the board */}
        <div style={{ position: "absolute", opacity: doc.o, left: interpolate(doc.t, [0, 1], [F_X + 70, B_X + 60]),
                      top: interpolate(doc.t, [0, 1], [CARD_Y + 120, CARD_Y + 8]), fontSize: 13, background: C.warn,
                      color: "#1b1a18", borderRadius: 8, padding: "6px 10px", fontWeight: 600 }}>📄 save_context</div>

        {/* caption */}
        {CAPTIONS.map(([a, b, text]) => (
          <div key={a} style={{ position: "absolute", left: 0, right: 0, top: 468, textAlign: "center", fontSize: 21,
                                fontWeight: 600, opacity: fade(f, a, a + 12, b - 10, b) }}>{text}</div>
        ))}

        {/* restart prompt */}
        <AbsoluteFill style={{ opacity: prompt, background: "rgba(10,10,9,.72)", justifyContent: "center", alignItems: "center" }}>
          <div style={{ width: 860, background: C.card, border: `1px solid ${C.line}`, borderRadius: 14, padding: "18px 22px" }}>
            <div style={{ fontSize: 14, color: C.muted, marginBottom: 10 }}>New Account 2 session · the two-line restart prompt</div>
            <div style={{ fontFamily: MONO, fontSize: 13.5, lineHeight: 1.7, color: C.text, minHeight: 46 }}>
              <div>{PROMPT[0].slice(0, typed)}</div>
              <div>{PROMPT[1].slice(0, Math.max(0, typed - PROMPT[0].length))}<span style={{ opacity: f % 20 < 10 ? 1 : 0 }}>▍</span></div>
            </div>
            <div style={{ fontSize: 14, color: C.ok, marginTop: 10, opacity: fade(f, 578, 586) }}>
              ✓ resume → Account 2's saved summary + task #1 with all its notes
            </div>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>

      {/* end card */}
      <AbsoluteFill style={{ opacity: end, justifyContent: "center", alignItems: "center" }}>
        <div style={{ width: 120, height: 18, borderRadius: 9, background: C.accent, marginBottom: 26 }} />
        <div style={{ fontSize: 64, fontWeight: 800 }}>Coshift</div>
        <div style={{ fontSize: 20, color: C.muted, marginTop: 10 }}>Usage-aware handovers · context-limit restarts · phone-friendly board</div>
        <div style={{ fontSize: 24, color: C.accent, marginTop: 26, fontFamily: MONO }}>github.com/pgamerx/coshift</div>
        <div style={{ fontSize: 15, color: C.muted, marginTop: 10 }}>Free and open source · MIT</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
