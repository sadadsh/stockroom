class KiCadError(Exception):
    pass


class KiCadFileError(KiCadError):
    pass


class KiCadCliError(KiCadError):
    pass
