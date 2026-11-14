import React from "react";
import ReactDOM from "react-dom/client";
import { McxDesk } from "./McxDesk";
import "../index.css";

try {
  if (localStorage.getItem("theme") === "light") document.documentElement.setAttribute("data-theme", "light");
} catch { /* private mode */ }

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <McxDesk />
  </React.StrictMode>
);
