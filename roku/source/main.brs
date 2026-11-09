' SaverSwap: plays the scene picked on the SaverSwap server full screen, with an
' optional clock/weather overlay and optional sound. Any remote button closes it.
'
' Roku doesn't allow video (or sound) in real screensavers, so SaverSwap is a
' regular app instead: the SaverSwap server watches the Roku and launches this app
' the moment the Roku's own screensaver starts. It can also be opened by hand.
' The server address is in pkg:/config.json, written by tools/install_roku.py.

sub Main(args as dynamic)
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.SetMessagePort(port)
    scene = screen.CreateScene("SaverScene")
    screen.Show()
    scene.observeField("done", port)  ' must come after Show(), or the event never arrives
    while true
        msg = wait(0, port)
        t = type(msg)
        if t = "roSGScreenEvent"
            if msg.IsScreenClosed() then return
        else if t = "roSGNodeEvent"
            if msg.GetField() = "done" and msg.GetData() = true
                screen.Close()
                return
            end if
        end if
    end while
end sub
