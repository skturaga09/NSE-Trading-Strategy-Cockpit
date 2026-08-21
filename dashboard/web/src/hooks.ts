import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// Shared query key so Header and the Trade Ideas tab reuse one cached fetch.
export function useRecommendations() {
  return useQuery({
    queryKey: ["recommendations"],
    queryFn: api.getRecommendations,
    refetchInterval: 60_000,
  });
}

export function biasColor(label?: string): string {
  if (label === "BULLISH") return "#22c55e";
  if (label === "BEARISH") return "#f43f5e";
  return "#eab308";
}
