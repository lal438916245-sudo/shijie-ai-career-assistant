import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import { PageBoundary } from "./components/WorkspaceQuality"
import "./index.css"
import "./design.css"
import "./workspace.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><PageBoundary><App /></PageBoundary></React.StrictMode>,
)
