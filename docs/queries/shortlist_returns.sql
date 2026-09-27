-- SCOPE Appendix D: shortlist with returns under all scenarios (runs once SiteFinancials has rows, M6).
SELECT f.parcel_id, f.stalls, f.noi, f.yield_on_cost, f.irr_10yr,
       MAX(CASE WHEN s.scenario = 'Balanced'    THEN s.rank END) AS rank_balanced,
       MAX(CASE WHEN s.scenario = 'DemandFirst' THEN s.rank END) AS rank_demand,
       MAX(CASE WHEN s.scenario = 'CostFirst'   THEN s.rank END) AS rank_cost
FROM SiteFinancials f JOIN SiteScores s USING (parcel_id, run_id)
WHERE f.run_id = :run_id
GROUP BY f.parcel_id, f.stalls, f.noi, f.yield_on_cost, f.irr_10yr
ORDER BY f.irr_10yr DESC LIMIT 10;
