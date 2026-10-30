import React from "react";
import { AbsoluteFill } from "remotion";

// Static README diagrams (rendered as PNG stills), same palette as the animation.
const C = {
  bg: "#1b1a18", card: "#252421", text: "#ecebe8", muted: "#a29f98", line: "#4a4740",
  accent: "#e0805e", ok: "#5cbf83", warn: "#e0a84a",
};
const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif';

type Box = { x: number; y: number; w: number; h: number };
const Node: React.FC<Box & { title: string; sub?: string; color?: string; dashed?: boolean }> =
  ({ x, y, w, h, title, sub, color = C.line, dashed }) => (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, boxSizing: "border-box",
                  background: dashed ? "rgba(224,128,94,.07)" : C.card, border: `2px ${dashed ? "dashed" : "solid"} ${color}`,
                  borderRadius: 16, display: "flex", flexDirection: "column", justifyContent: "center",
                  alignItems: "center", textAlign: "center", padding: 10 }}>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{title}</div>
      {sub ? <div style={{ fontSize: 15, color: C.muted, marginTop: 6, lineHeight: 1.35, whiteSpace: "pre-line" }}>{sub}</div> : null}
    </div>
  );

// Straight arrow from (x1,y1) to (x2,y2) with a label at its middle.
const Arrow: React.FC<{ x1: number; y1: number; x2: number; y2: number; label: string; color?: string; dy?: number }> =
  ({ x1, y1, x2, y2, label, color = C.muted, dy = -12 }) => (
    <>
      <svg style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} width={1} height={1}>
        <defs>
          <marker id={`m${x1}${y1}`} markerWidth="12" markerHeight="12" refX="11" refY="6" orient="auto"
                  markerUnits="userSpaceOnUse">
            <path d="M0,0 L12,6 L0,12 z" fill={color} />
          </marker>
        </defs>
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={2.5} markerEnd={`url(#m${x1}${y1})`} />
      </svg>
      <div style={{ position: "absolute", left: (x1 + x2) / 2 - 200, width: 400, top: (y1 + y2) / 2 + dy - 10,
                    textAlign: "center", fontSize: 14, color: C.text, whiteSpace: "nowrap" }}>
        <span style={{ background: C.bg, padding: "2px 6px" }}>{label}</span>
      </div>
    </>
  );

export const HowItWorks: React.FC = () => (
  <AbsoluteFill style={{ background: C.bg, color: C.text, fontFamily: FONT }}>
    <div style={{ position: "absolute", left: 40, top: 28, fontSize: 26, fontWeight: 800 }}>How it works</div>
    <Node x={30} y={110} w={230} h={110} title="WORK session" sub="Claude Code, cloud or desktop" color={C.accent} />
    <Node x={30} y={300} w={230} h={110} title="PERSONAL session" sub="Claude Code, cloud or desktop" color={C.accent} />
    <Node x={495} y={170} w={250} h={180} title="Coshift board" sub={"Vercel + Upstash Redis\ntasks · notes · usage · context"} dashed color={C.accent} />
    <Node x={975} y={70} w={210} h={100} title="You" sub="board page, on your phone" />
    <Node x={975} y={210} w={210} h={100} title="Live limits" sub="status line / usage pusher" />
    <Node x={975} y={350} w={210} h={100} title="Context hook" sub="runs after tool calls" />
    <Arrow x1={260} y1={165} x2={493} y2={230} label="claim · notes · save_context" />
    <Arrow x1={260} y1={355} x2={493} y2={290} label="each with its own token" dy={14} />
    <Arrow x1={973} y1={120} x2={747} y2={210} label="tasks · guidance · messages" />
    <Arrow x1={973} y1={260} x2={747} y2={260} label="5-hour + weekly % + window" color={C.warn} />
    <Arrow x1={973} y1={400} x2={747} y2={310} label="context %" color={C.ok} dy={14} />
    <div style={{ position: "absolute", left: 40, right: 40, top: 470, fontSize: 17, color: C.muted, textAlign: "center" }}>
      Sessions coordinate through the board, not through you. Each token tells the board which account is calling.
    </div>
  </AbsoluteFill>
);

// A small sequence diagram: lanes across, steps down.
const LANES = ["You", "WORK", "Board", "PERSONAL", "New session"];
const laneX = (i: number) => 110 + i * 245;
type Step = { from: number; to: number; text: string; color?: string } | { note: string; color: string };
const STEPS: Step[] = [
  { from: 0, to: 1, text: "Split the checkout work into tasks" },
  { from: 1, to: 2, text: "add_task ×5 · claim_task → #1" },
  { from: 3, to: 2, text: "claim_task → #2 (never the same task)" },
  { note: "WORK reaches 85% of its 5-hour limit", color: C.warn },
  { from: 1, to: 2, text: "release_task #1 + handover note", color: C.warn },
  { from: 3, to: 2, text: "claim_task → #1 with all its notes" },
  { note: "Later: a session's context reaches 70%", color: C.ok },
  { from: 1, to: 2, text: "save_context: goal, state, branch, next step", color: C.ok },
  { from: 1, to: 0, text: "two-line restart prompt", color: C.ok },
  { from: 4, to: 2, text: "board resume → summary + claimed task", color: C.ok },
];

export const TypicalDay: React.FC = () => {
  const top = 120, row = 50;
  const bottom = top + STEPS.length * row + 10;
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.text, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 40, top: 28, fontSize: 26, fontWeight: 800 }}>A typical day with several accounts</div>
      {LANES.map((name, i) => (
        <React.Fragment key={name}>
          <div style={{ position: "absolute", left: laneX(i) - 85, top: 74, width: 170, textAlign: "center", fontSize: 17,
                        fontWeight: 700, padding: "8px 0", borderRadius: 10, background: C.card,
                        border: `2px solid ${name === "Board" ? C.accent : C.line}` }}>{name}</div>
          <div style={{ position: "absolute", left: laneX(i) - 1, top: 116, width: 2, height: bottom - 116, background: C.line }} />
        </React.Fragment>
      ))}
      {STEPS.map((s, k) => {
        const y = top + k * row + 25;
        if ("note" in s) {
          return (
            <div key={k} style={{ position: "absolute", left: laneX(1) - 60, width: laneX(3) - laneX(1) + 120, top: y - 16,
                                  textAlign: "center", fontSize: 15, fontWeight: 600, color: "#1b1a18", background: s.color,
                                  borderRadius: 8, padding: "6px 0" }}>{s.note}</div>
          );
        }
        return <Arrow key={k} x1={laneX(s.from)} y1={y} x2={laneX(s.to) + (s.to > s.from ? -4 : 4)} y2={y}
                      label={s.text} color={s.color} dy={-11} />;
      })}
    </AbsoluteFill>
  );
};
