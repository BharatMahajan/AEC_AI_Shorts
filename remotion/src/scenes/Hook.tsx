import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const Hook: React.FC<{
  hook: string;
  title: string;
  accent: string;
  contentBottomInset?: number;
}> = ({ hook, title, accent, contentBottomInset = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 } });
  const y = interpolate(enter, [0, 1], [40, 0]);

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
      <div style={{ transform: `translateY(${y}px)`, opacity: enter, textAlign: "center" }}>
        <div
          style={{
            display: "inline-block",
            padding: "12px 28px",
            borderRadius: 999,
            backgroundColor: `${accent}22`,
            color: accent,
            fontFamily: "Inter, Arial, sans-serif",
            fontSize: 34,
            fontWeight: 700,
            letterSpacing: 2,
            marginBottom: 40,
          }}
        >
          {title.toUpperCase()}
        </div>
        <div
          style={{
            color: "white",
            fontFamily: "Inter, Arial, sans-serif",
            fontSize: 92,
            fontWeight: 900,
            lineHeight: 1.05,
            textShadow: "0 6px 28px rgba(0,0,0,0.55)",
          }}
        >
          {hook}
        </div>
      </div>
    </AbsoluteFill>
  );
};
