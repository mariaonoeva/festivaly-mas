import dataset from "../data/festivals.json";
import FestivalBrowser from "../components/FestivalBrowser";
import { currentPragueDate } from "../lib/festivals";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <FestivalBrowser
      festivals={dataset.festivals}
      generated={dataset.generated}
      today={currentPragueDate()}
    />
  );
}
