import { ComponentsPage } from "./pages/ComponentsPage";

// The first vertical slice is a single page. When Projects and Bench arrive the
// rail turns into a router; for now the Components page is the whole app.
export default function App() {
  return <ComponentsPage />;
}
