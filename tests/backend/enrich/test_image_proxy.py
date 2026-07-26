"""The product-image proxy (owner 2026-07-24: "the pulled images dont render").

The pulled product photo travels as specs["Image"] (a vendor CDN URL). A bare <img>
hotlink can be refused by the vendor's CDN (Mouser sits behind Akamai), so the SPA
falls back to this backend proxy: fetch the image server-side with a browser-like
identity, cache the bytes on disk under the enrich cache, and serve them to the SPA.
Only ever fetches plainly-public https URLs (never loopback/private targets - the
URL originates from remote page content, so it is treated as hostile input)."""
from __future__ import annotations

from stockroom.enrich.image_proxy import (
    allowed_image_url,
    cache_path_for,
    fetch_product_image,
    sniff_image_type,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
GIF = b"GIF89a" + b"\x00" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20


def test_allowed_image_url_https_public_hosts_only():
    assert allowed_image_url("https://mm.digikey.com/Images/x.jpg") is True
    assert allowed_image_url("https://www.mouser.com/images/ti/images/x.jpg") is True
    # never plain http (the token-guarded local API must not be made to fetch cleartext),
    # never a scheme that is not http(s) at all
    assert allowed_image_url("http://www.mouser.com/x.jpg") is False
    assert allowed_image_url("ftp://mouser.com/x.jpg") is False
    assert allowed_image_url("file:///etc/passwd") is False
    assert allowed_image_url("") is False
    assert allowed_image_url("not a url") is False
    # never a loopback / private / IP-literal target: the URL comes from remote content,
    # and this endpoint must not be usable to probe the machine or the LAN
    assert allowed_image_url("https://localhost/x.png") is False
    assert allowed_image_url("https://127.0.0.1:8477/api/system") is False
    assert allowed_image_url("https://[::1]/x.png") is False
    assert allowed_image_url("https://10.0.0.7/x.png") is False
    assert allowed_image_url("https://192.168.1.10/x.png") is False
    assert allowed_image_url("https://intranet.local/x.png") is False


def test_sniff_image_type_recognizes_the_real_formats():
    assert sniff_image_type(PNG) == "image/png"
    assert sniff_image_type(JPG) == "image/jpeg"
    assert sniff_image_type(GIF) == "image/gif"
    assert sniff_image_type(WEBP) == "image/webp"
    assert sniff_image_type(b"  <svg xmlns='x'></svg>") == "image/svg+xml"
    # an HTML block page (Akamai challenge) is NOT an image and must never be served as one
    assert sniff_image_type(b"<!DOCTYPE html><html>...") is None
    assert sniff_image_type(b"") is None


def test_fetch_product_image_fetches_once_then_serves_the_cache(tmp_path):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return PNG

    url = "https://mm.digikey.com/Images/part.png"
    got = fetch_product_image(url, tmp_path, fetch=fake_fetch)
    assert got == (PNG, "image/png")
    assert cache_path_for(url, tmp_path).exists()
    # second read never re-fetches: the cache serves it
    again = fetch_product_image(url, tmp_path, fetch=fake_fetch)
    assert again == (PNG, "image/png")
    assert calls == [url]


def test_fetch_product_image_never_caches_a_non_image(tmp_path):
    # a CDN that answers with an HTML challenge page must yield None - and must NOT poison
    # the cache, so a later attempt (challenge passed) can still succeed
    url = "https://www.mouser.com/images/x.jpg"
    got = fetch_product_image(url, tmp_path, fetch=lambda u: b"<html>blocked</html>")
    assert got is None
    assert not cache_path_for(url, tmp_path).exists()


def test_fetch_product_image_disallowed_url_never_fetches(tmp_path):
    def boom(url):
        raise AssertionError("must not fetch a disallowed url")

    assert fetch_product_image("https://127.0.0.1/x.png", tmp_path, fetch=boom) is None
    assert fetch_product_image("http://mouser.com/x.png", tmp_path, fetch=boom) is None


def test_fetch_product_image_degrades_on_a_fetch_failure(tmp_path):
    def dead(url):
        raise OSError("network down")

    got = fetch_product_image("https://mm.digikey.com/x.png", tmp_path, fetch=dead)
    assert got is None


def test_cache_path_is_stable_and_scoped_under_an_images_dir(tmp_path):
    url = "https://mm.digikey.com/Images/part.png"
    p1 = cache_path_for(url, tmp_path)
    p2 = cache_path_for(url, tmp_path)
    assert p1 == p2
    assert p1.parent == tmp_path / "images"
    assert cache_path_for("https://other/x.png", tmp_path) != p1
