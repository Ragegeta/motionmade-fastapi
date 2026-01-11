"""Tests for normalize.py"""

from app.normalize import normalize_message


def test_hw_normalizes_to_how():
    """Test that 'hw' normalizes to 'how'"""
    result = normalize_message("hw much 4 sparky")
    assert "how" in result
    assert "for" in result  # also test that 4 -> for still works


def test_pwr_normalizes_to_power():
    """Test that 'pwr' normalizes to 'power'"""
    result = normalize_message("pwr out half house")
    assert "power" in result


def test_saftey_swich_goin_normalize():
    """Test safety, switch, and going typos normalize correctly"""
    result = normalize_message("saftey swich keeps goin off")
    assert "safety" in result
    assert "switch" in result
    assert "going" in result


def test_plumbr_normalizes_to_plumber():
    """Test that 'plumbr' normalizes to 'plumber'"""
    result = normalize_message("need plumbr asap")
    assert "plumber" in result


def test_panls_normalizes_to_panels():
    """Test that 'panls' normalizes to 'panels'"""
    result = normalize_message("solar panls broken")
    assert "panels" in result


def test_flickring_normalizes_to_flickering():
    """Test that 'flickring' normalizes to 'flickering'"""
    result = normalize_message("lights flickring heaps")
    assert "flickering" in result


def test_beepin_normalizes_to_beeping():
    """Test that 'beepin' normalizes to 'beeping'"""
    result = normalize_message("smok alarm wont stop beepin")
    assert "beeping" in result


def test_licenced_normalizes_to_licensed():
    """Test that 'licenced' normalizes to 'licensed'"""
    result = normalize_message("r u licenced")
    assert "licensed" in result
    assert "are" in result  # also test that r -> are works
    assert "you" in result  # also test that u -> you works


def test_cn_normalizes_to_can():
    """Test that 'cn' normalizes to 'can'"""
    result = normalize_message("cn u come 2day")
    assert "can" in result
    assert "you" in result  # also test that u -> you works


def test_switchbord_normalizes_to_switchboard():
    """Test that 'switchbord' normalizes to 'switchboard'"""
    result = normalize_message("switchbord making noise")
    assert "switchboard" in result


def test_aircon_normalizes_to_air_con():
    """Test that 'aircon' normalizes to 'air con'"""
    result = normalize_message("aircon busted")
    assert "air con" in result

