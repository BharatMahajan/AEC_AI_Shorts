import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

export const ProgressBar: React.FC<{ accent: string }> = ({ accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const pct = Math.min(1, frame / Math.max(1, durationInFrames));
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start" }}>
      <div style={{ height: 10, width: "100%", backgroundColor: "rgba(255,255,255,0.12)" }}>
        <div style={{ height: "100%", width: `${pct * 100}%`, backgroundColor: accent }} />
      </div>
    </AbsoluteFill>
  );
};
