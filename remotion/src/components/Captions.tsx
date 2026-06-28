import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Always-on large captions driven purely by the caption list and the clip
// length — NEVER gated on word timings (plan §8: word timings drift and have
// produced blank caption tracks). Each caption shows for an equal slice.
export const Captions: React.FC<{ captions: string[]; accent: string }> = ({
  captions,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  if (captions.length === 0) return null;

  const per = durationInFrames / captions.length;
  const idx = Math.min(captions.length - 1, Math.floor(frame / per));
  const local = frame - idx * per;
  const appear = interpolate(local, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        padding: "0 64px 150px",
      }}
    >
      <div
        style={{
          opacity: appear,
          transform: `translateY(${(1 - appear) * 30}px)`,
          textAlign: "center",
          color: "white",
          fontFamily: "Inter, Arial, sans-serif",
          fontSize: 52,
          fontWeight: 800,
          lineHeight: 1.15,
          textShadow: "0 4px 24px rgba(0,0,0,0.6)",
          maxWidth: 900,
          backgroundColor: "rgba(0, 0, 0, 0.45)",
          borderRadius: 24,
          padding: "22px 28px",
        }}
      >
        <span style={{ boxShadow: `0 6px 0 ${accent}`, borderRadius: 4 }}>
          {captions[idx]}
        </span>
      </div>
    </AbsoluteFill>
  );
};
