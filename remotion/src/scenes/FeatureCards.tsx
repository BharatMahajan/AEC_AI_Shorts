import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { ShortProps } from "../schema";

type Point = ShortProps["points"][number];

export const FeatureCards: React.FC<{
  points: Point[];
  accent: string;
  contentBottomInset?: number;
}> = ({ points, accent, contentBottomInset = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const shown = points.slice(0, 2); // the 1-2 concrete features

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        paddingTop: 64,
        paddingLeft: 64,
        paddingRight: 64,
        paddingBottom: 64 + contentBottomInset,
        gap: 40,
      }}
    >
      {shown.map((p, i) => {
        const delay = i * 10;
        const enter = spring({ frame: frame - delay, fps, config: { damping: 200 } });
        const x = interpolate(enter, [0, 1], [i % 2 === 0 ? -60 : 60, 0]);
        return (
          <div
            key={i}
            style={{
              opacity: enter,
              transform: `translateX(${x}px)`,
              width: "100%",
              borderRadius: 28,
              padding: 40,
              backgroundColor: "rgba(255,255,255,0.06)",
              borderLeft: `10px solid ${accent}`,
            }}
          >
            <div
              style={{
                color: accent,
                fontFamily: "Inter, Arial, sans-serif",
                fontSize: 46,
                fontWeight: 800,
                marginBottom: 14,
              }}
            >
              {p.heading}
            </div>
            <div
              style={{
                color: "white",
                fontFamily: "Inter, Arial, sans-serif",
                fontSize: 38,
                fontWeight: 500,
                lineHeight: 1.25,
              }}
            >
              {p.detail}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
