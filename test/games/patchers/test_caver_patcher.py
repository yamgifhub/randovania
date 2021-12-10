import json
from pathlib import Path
import pytest
from unittest.mock import PropertyMock

from randovania.games.cave_story.layout.cs_cosmetic_patches import CSCosmeticPatches, CSMusic, CSSong, MusicRandoType, MyChar
from randovania.interface_common.players_configuration import PlayersConfiguration
from randovania.games.cave_story.patcher.caver_patcher import CaverPatcher
from randovania.layout.layout_description import LayoutDescription


@pytest.mark.parametrize("rdvgame", [
    "start",
    "arthur",
    "camp",
])
def test_create_patch_data_layout(test_files_dir, mocker, rdvgame):
    _create_patch_data(test_files_dir, mocker, rdvgame, rdvgame, CSCosmeticPatches())

@pytest.mark.parametrize("patches", [
    ("shuffle", CSCosmeticPatches(mychar=MyChar.SUE, music_rando=CSMusic(randomization_type=MusicRandoType.SHUFFLE, song_status=CSSong.defaults()))),
    ("random", CSCosmeticPatches(mychar=MyChar.CUSTOM, music_rando=CSMusic(randomization_type=MusicRandoType.RANDOM, song_status=CSSong.defaults()))),
    ("chaos", CSCosmeticPatches(mychar=MyChar.RANDOM, music_rando=CSMusic(randomization_type=MusicRandoType.CHAOS, song_status=CSSong.defaults()))),
])
def test_create_patch_data_cosmetic(test_files_dir, mocker, patches):
    test_file, cosmetic_patches = patches
    _create_patch_data(test_files_dir, mocker, "arthur", test_file, cosmetic_patches)

def _create_patch_data(test_files_dir, mocker, in_file, out_file, cosmetic):
    # Setup
    f = test_files_dir.joinpath("log_files", "cave_story", f"{in_file}.rdvgame")
    description = LayoutDescription.from_file(f)
    patcher = CaverPatcher()
    players_config = PlayersConfiguration(0, {0: "Cave Story"})

    mocker.patch(
        "randovania.layout.layout_description.LayoutDescription._shareable_hash_bytes",
        new_callable=PropertyMock,
        return_value=b'\x00\x00\x00\x00\x00'
    )

    # Run
    data = patcher.create_patch_data(description, players_config, cosmetic)

    # Expected Result

    # strip mychar to just the filename rather than full path
    if data["mychar"] is not None:
        mychar = Path(data["mychar"])
        data["mychar"] = mychar.name
    
    # Uncomment the following lines to update:
    # with test_files_dir.joinpath("caver_expected_data", f"{out_file}.json").open("w") as f:
    #     json.dump(data, f)
    # assert data == {}
    
    with test_files_dir.joinpath("caver_expected_data", f"{out_file}.json").open("r") as f:
        expected_data = json.load(f)
    
    assert data == expected_data