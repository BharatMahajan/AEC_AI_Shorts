import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const CTA: React.FC<{
  cta: string;
  accent: string;
  contentBottomInset?: number;
}> = ({ cta, accent, contentBottomInset = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 12, stiffness: 120 } });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        paddingTop: 64,
        paddingLeft: 64,
        paddingRight: 64,
        paddingBottom: 64 + contentBottomInset,
      }}
    >
      <div
        style={{
          transform: `scale(${0.8 + pop * 0.2})`,
          opacity: pop,
          textAlign: "center",
          padding: "48px 56px",
          borderRadius: 36,
          backgroundColor: accent,
          color: "#0B0F17",
          fontFamily: "Inter, Arial, sans-serif",
          fontSize: 70,
          fontWeight: 900,
          lineHeight: 1.1,
          boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
        }}
      >
        {cta}
      </div>
    </AbsoluteFill>
  );
};
