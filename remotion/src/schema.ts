import { z } from "zod";

// The render-props contract. MUST mirror pipeline/render_props.REQUIRED_PROP_KEYS
// — a Python golden test asserts every camelCase key here is produced by
// build_render_props(). Keep the two in lockstep.
export const PointSchema = z.object({
  heading: z.string(),
  detail: z.string(),
});

export const ShortPropsSchema = z.object({
  version: z.number(),
  durationInFrames: z.number(),
  fps: z.number(),
  width: z.number(),
  height: z.number(),
  audioSrc: z.string(),
  bucket: z.string(),
  accent: z.string(),
  pattern: z.string(),
  hookStyle: z.string(),
  title: z.string(),
  hook: z.string(),
  captions: z.array(z.string()),
  points: z.array(PointSchema),
  flow: z.array(z.string()),
  cta: z.string(),
});

export type ShortProps = z.infer<typeof ShortPropsSchema>;

export const defaultProps: ShortProps = {
  version: 1,
  durationInFrames: 1650,
  fps: 30,
  width: 1080,
  height: 1920,
  audioSrc: "voice.mp3",
  bucket: "bim_authoring",
  accent: "#4F8DFD",
  pattern: "grid",
  hookStyle: "question",
  title: "AI in Revit",
  hook: "What if Revit designed your floorplate for you?",
  captions: [
    "Autodesk Forma uses generative design to test hundreds of options.",
    "Inside Revit, AI tagging and clash detection cut coordination time.",
    "Follow for one AEC AI workflow every day!",
  ],
  points: [
    { heading: "Generative massing", detail: "Forma scores daylight automatically" },
    { heading: "Clash detection", detail: "Navisworks ranks clashes by severity" },
  ],
  flow: ["model", "analyze", "coordinate"],
  cta: "Follow for daily AEC AI workflows!",
};
