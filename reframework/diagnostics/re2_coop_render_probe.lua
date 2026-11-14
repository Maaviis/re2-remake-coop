-- Opt-in RE2 render diagnostic. Copy to autorun only for an isolated test.
if reframework:get_game_name() ~= "re2" then return end

local reported = false
re.on_frame(function()
    draw.filled_rect(900, 80, 400, 100, 0xFFFF00FF)
    draw.text("RE2 COOP DRAW PROBE", 920, 120, 0xFFFFFFFF)
    imgui.set_next_window_pos({950, 240}, 1)
    imgui.set_next_window_size({500, 180}, 1)
    imgui.begin_window("RE2 Coop Minimal Render Probe", nil, 0)
    imgui.text("MINIMAL IMGUI WINDOW")
    local pos, size = imgui.get_window_pos(), imgui.get_window_size()
    imgui.end_window()
    if not reported then
        local screen = imgui.get_display_size()
        log.info(string.format("RE2_COOP_RENDER_PROBE display=%.0fx%.0f pos=%.0f,%.0f size=%.0fx%.0f menu=%s",
            screen.x, screen.y, pos.x, pos.y, size.x, size.y, tostring(reframework:is_drawing_ui())))
        reported = true
    end
end)
