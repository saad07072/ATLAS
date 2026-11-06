"use client";

import type { JSX } from "react";
import { AtlasCore } from "@/components/jarvis/jarvis-core";

export default function OverlayPage(): JSX.Element {
  return <AtlasCore initialMini={true} isStandaloneOverlay={true} />;
}
