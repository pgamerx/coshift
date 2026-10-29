import { Composition } from "remotion";
import { Baton } from "./Baton";

export const Root = () => (
  <Composition id="Baton" component={Baton} durationInFrames={690} fps={30} width={960} height={540} />
);
