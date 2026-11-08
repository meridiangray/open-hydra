#include <saucer/webview.hpp>
#include "chrome.hpp"

#include <charconv>
#include <iostream>
#include <string>
#include <string_view>

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#include <dwmapi.h>
#include <wrl/client.h>
#include <saucer/modules/stable/webview2.hpp>
#endif

void open_external(const saucer::url &url)
{
#ifdef _WIN32
    const auto text = url.string();
    const auto size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.c_str(), -1, nullptr, 0);
    if (!size)
        return;
    std::wstring wide(size, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.c_str(), -1, wide.data(), size);
    ShellExecuteW(nullptr, L"open", wide.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
#endif
}

int main(int argc, char **argv)
{
    if (argc < 2 || argc > 3 || (argc == 3 && std::string_view(argv[2]) != "--smoke-test"))
    {
        std::cerr << "Start with python -m hydra.desktop ARCHIVE (this shell takes a local wiki URL).\n";
        return 2;
    }

    const std::string address = argv[1];
    const auto origin = saucer::url::parse(address);
    if (!origin || origin->scheme() != "http" || origin->host() != "127.0.0.1" || !origin->port() ||
        origin->user() || origin->password())
    {
        std::cerr << "The desktop shell only opens a loopback Hydra wiki.\n";
        return 2;
    }

    auto app = saucer::application::create({.id = "org.openhydra.desktop", .argc = argc, .argv = argv});
    if (!app)
    {
        std::cerr << app.error().message() << '\n';
        return 1;
    }

    int result = 0;
    return app->run([&](saucer::application *application) -> coco::stray {
        auto created_window = saucer::window::create(application);
        if (!created_window)
        {
            std::cerr << created_window.error().message() << '\n';
            result = 1;
            application->quit();
            co_return;
        }
        auto window = created_window.value();
        auto created_view = saucer::webview::create({
            .window = window,
            .attributes = true,
#ifdef _WIN32
            .browser_flags = {"--enable-features=BackForwardCache"},
#endif
        });
        if (!created_view)
        {
            std::cerr << created_view.error().message() << '\n';
            result = 1;
            application->quit();
            co_return;
        }
        auto view = std::move(created_view).value();
#ifdef _WIN32
        Microsoft::WRL::ComPtr<ICoreWebView2Settings> settings;
        Microsoft::WRL::ComPtr<ICoreWebView2Settings9> regions;
        if (SUCCEEDED(view.native().webview->get_Settings(&settings)) && SUCCEEDED(settings.As(&regions)))
            regions->put_IsNonClientRegionSupportEnabled(TRUE);
#endif
        view.inject({.code = hydra_desktop_chrome, .run_at = saucer::script::time::creation, .clearable = false});
        window->set_decorations(saucer::window::decoration::partial);
        window->set_title("Hydra");
        window->set_size({1280, 900});
        window->set_min_size({800, 600});
        view.on<saucer::webview::event::navigate>([&](const saucer::navigation &navigation) {
            const auto target = navigation.url();
            if (target.scheme() == origin->scheme() && target.host() == origin->host() &&
                target.port() == origin->port() && !target.user() && !target.password())
                return saucer::policy::allow;
            if (navigation.user_initiated() && (target.scheme() == "https" || target.scheme() == "http") &&
                !target.user() && !target.password())
                open_external(target);
            return saucer::policy::block;
        });
        view.on<saucer::webview::event::title>([&](std::string_view title) {
            const auto text = std::string(title) + " — Hydra";
            window->set_title(text.c_str());
        });
        view.on<saucer::webview::event::message>([&](std::string_view message) {
            constexpr std::string_view prefix = "hydra:chrome:";
            if (!message.starts_with(prefix) || message.size() != prefix.size() + 6)
                return saucer::status::unhandled;
            unsigned int rgb = 0;
            const auto parsed = std::from_chars(message.data() + prefix.size(), message.data() + message.size(), rgb, 16);
            if (parsed.ec != std::errc{} || parsed.ptr != message.data() + message.size())
                return saucer::status::unhandled;
            const saucer::color color{static_cast<std::uint8_t>(rgb >> 16), static_cast<std::uint8_t>(rgb >> 8),
                                      static_cast<std::uint8_t>(rgb), 255};
            window->set_background(color);
            view.set_background(color);
#ifdef _WIN32
            const COLORREF border = RGB(color.r, color.g, color.b);
            const BOOL dark = color.r * 299 + color.g * 587 + color.b * 114 < 128000;
            const auto hwnd = window->native().hwnd;
            DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, &border, sizeof(border));
            DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));
#endif
            return saucer::status::handled;
        });
        window->on<saucer::window::event::maximize>([&](bool maximized) {
            view.execute(maximized ? "dispatchEvent(new CustomEvent('hydra-window-maximized',{detail:true}))"
                                   : "dispatchEvent(new CustomEvent('hydra-window-maximized',{detail:false}))");
        });
        if (argc == 3)
        {
            view.on<saucer::webview::event::load>([&](saucer::state state) {
                if (state == saucer::state::finished)
                {
                    std::cout << "Hydra desktop: wiki loaded in WebView2\n";
                    application->quit();
                }
            });
        }
        view.set_url(address.c_str());
        window->show();
        co_await application->finish();
    }) || result;
}
