import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// Shared query key so Header and the Trade Ideas tab reuse one cached fetch.
export function useRecommendations() {
  return useQuery({
    queryKey: ["recommendations"],
    queryFn: api.getRecommendations,
    // Poll fast while the real VCP screen is still warming, then settle to 60s.
    refetchInterval: (q) =>
      q.state.data?.ideas_source === "modeled snapshot" ? 6000 : 60_000,
  });
}

export function biasColor(label?: string): string {
  if (label === "BULLISH") return "var(--green)";
  if (label === "BEARISH") return "var(--red)";
  return "var(--gold)";
}
