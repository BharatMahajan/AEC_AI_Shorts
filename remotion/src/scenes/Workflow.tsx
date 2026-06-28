import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Renders the script's `flow` as a left-to-right step diagram — ideal for the
// clash -> resolve -> coordinate style workflows in the AEC buckets.
export const Workflow: React.FC<{
  flow: string[];
  accent: string;
  contentBottomInset?: number;
}> = ({ flow, accent, contentBottomInset = 0 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const steps = flow.slice(0, 4);
  if (steps.length === 0) return null;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        paddingTop: 56,
        paddingLeft: 56,
        paddingRight: 56,
        paddingBottom: 56 + contentBottomInset,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 28, width: "100%" }}>
        {steps.map((s, i) => {
          const start = (i / steps.length) * (durationInFrames * 0.4);
          const reveal = interpolate(frame, [start, start + 12], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <div
              key={i}
              style={{
                opacity: reveal,
                transform: `scale(${0.9 + reveal * 0.1})`,
                display: "flex",
                alignItems: "center",
                gap: 24,
              }}
            >
              <div
                style={{
                  minWidth: 88,
                  height: 88,
                  borderRadius: 20,
                  backgroundColor: accent,
                  color: "#0B0F17",
                  fontFamily: "Inter, Arial, sans-serif",
                  fontSize: 44,
                  fontWeight: 900,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {i + 1}
              </div>
              <div
                style={{
                  color: "white",
                  fontFamily: "Inter, Arial, sans-serif",
                  fontSize: 44,
                  fontWeight: 700,
                  textTransform: "capitalize",
                }}
              >
                {s}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
