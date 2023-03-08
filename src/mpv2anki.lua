seconds_to_replay = 2.25

function seconds_to_time(time)
    hours = math.floor(time / 3600)
    mins = math.floor(time / 60) % 60
    secs = math.floor(time % 60)
    milliseconds = (time * 1000) % 1000

    return string.format("%02d:%02d:%02d.%03d", hours, mins, secs, milliseconds)
end

function set_start_timestamp()
    start_timestamp = mp.get_property_number("time-pos")
    mp.osd_message("Start: " .. seconds_to_time(start_timestamp))
end

function set_end_timestamp()
    end_timestamp = mp.get_property_number("time-pos")
    mp.osd_message("End: " .. seconds_to_time(end_timestamp))
end

function reset_timestamps(flag)
    start_timestamp = nil
    end_timestamp = nil

    if timer ~= nil then
        timer:kill()
    end

    if periodic_timer ~= nil then
        periodic_timer:kill()
    end

    if flag ~= "no-osd" then
        local ass_start = mp.get_property_osd("osd-ass-cc/0")
        mp.osd_message(ass_start .. "{\\1c&HE6E6E6&}●", 0.5)
    end
end

function replay_the_first_seconds()
    if start_timestamp ~= nil then
        mp.commandv("seek", start_timestamp, "absolute+exact")
        mp.set_property("pause", "no")
        player_state = "replay the first seconds"
    end
end

function replay_the_last_seconds()
    if end_timestamp ~= nil then
        mp.commandv("seek", end_timestamp - seconds_to_replay, "absolute+exact")
        mp.set_property("pause", "no")
        player_state = "replay the last seconds"
    end
end

function stop_playback()
    player_state = nil
    mp.set_property("pause", "yes")

    if periodic_timer ~= nil then
        periodic_timer:kill()
    end
end

function playback_osd_message()
    mp.osd_message("●", 0.25)
end

function on_pause_change(name, value)
    if player_state == "replay" then
        if value == true then
            timer:stop()
        else
            timer:resume()
        end
    end
end

function on_seek()
    if timer ~= nil then
        timer:kill()
    end

    if periodic_timer ~= nil then
        periodic_timer:kill()
    end

    if player_state == "replay the last seconds" then
        periodic_timer = mp.add_periodic_timer(0.05, playback_osd_message)
    elseif player_state == "replay the first seconds" and end_timestamp ~= nil and end_timestamp > start_timestamp then
        periodic_timer = mp.add_periodic_timer(0.05, playback_osd_message)
    else
        player_state = nil
    end
end

function on_playback_restart()
    if player_state == "replay the first seconds" and end_timestamp == nil then
        player_state = nil
    elseif player_state == "replay the first seconds" and end_timestamp ~= nil and end_timestamp > start_timestamp then
        timer = mp.add_timeout(end_timestamp - start_timestamp, stop_playback)
        player_state = "replay"
    elseif player_state == "replay the last seconds" then
        timer = mp.add_timeout(seconds_to_replay, stop_playback)
        player_state = "replay"
    end
end

function create_anki_card(word)
    local time_pos = mp.get_property_number("time-pos")
    local status_msg = ""
    local sub_text = ""

    if word == nil then
        word = ""
    end

    if mp.get_property("sub-text") ~= nil then
        sub_text = mp.get_property("sub-text")
    end

    if start_timestamp ~= nil and end_timestamp ~= nil and end_timestamp > start_timestamp then
        status_msg = "[mpv2anki] " .. time_pos .. " # " .. start_timestamp .. " # " .. end_timestamp .. " # " .. word .. " # " .. sub_text
    elseif start_timestamp ~= nil and start_timestamp < time_pos then
        status_msg = "[mpv2anki] " .. time_pos .. " # " .. start_timestamp .. " # " .. "-1" .. " # " .. word .. " # " .. sub_text
    else
        status_msg = "[mpv2anki] " .. time_pos .. " # " .. "-1" .. " # " .. "-1" .. " # " .. word .. " # " .. sub_text
    end

    mp.set_property("term-status-msg", status_msg)
    mp.add_timeout("0.25", reset_property)

    reset_timestamps("no-osd")
end

function onclick()
    local mouse_pos = mp.get_property_native('mouse-pos')
    local osd_width = mp.get_property_number('osd-width')
    local osd_height = mp.get_property_number('osd-height')
    local pos = mouse_pos["x"] / osd_width
    if osd_height - mouse_pos["y"] <= 90 then
        return
    end
    if pos <= 0.33 then
        mp.commandv("sub-seek", -1)
    elseif pos >= 0.66 then
        mp.commandv("sub-seek", 1)
    else
        mp.set_property_bool("pause", not mp.get_property_bool("pause"))
    end
end

function reset_property()
    mp.set_property("term-status-msg", "")
end

mp.register_event("seek", on_seek)
mp.register_event("playback-restart", on_playback_restart)
mp.observe_property("pause", "bool", on_pause_change)

mp.add_key_binding("w", "set-start-timestamp", set_start_timestamp)
mp.add_key_binding("e", "set-end-timestamp", set_end_timestamp)
mp.add_key_binding("ctrl+w", "replay-the-first-seconds", replay_the_first_seconds)
mp.add_key_binding("ctrl+e", "replay-the-last-seconds", replay_the_last_seconds)
mp.add_key_binding("ctrl+r", "reset-timestamps", reset_timestamps)
mp.add_key_binding("b", "create-anki-card", create_anki_card)
-- mp.add_key_binding("MBTN_LEFT", "on-click", onclick)
mp.register_script_message("create-anki-word-card", create_anki_card)
