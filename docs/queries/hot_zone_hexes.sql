-- SCOPE Appendix D: hot-zone hexes. Hexes with unmet demand on a weekday daytime AND in an
-- evening or at an event (weekday evening, weekend evening or event). Used by `parkiq sql-check`,
-- which requires the count to equal the hexes the gap step qualified.
SELECT d.hex_id
FROM Hex_Gap_Daypart d
JOIN Hex_Gap_Daypart e ON e.hex_id = d.hex_id AND e.daypart IN ('wd_eve', 'we_eve', 'event') AND e.gap_stalls > 0
WHERE d.daypart = 'wd_day' AND d.gap_stalls > 0
GROUP BY d.hex_id;
