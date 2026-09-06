class CharacterUseRequest {
  const CharacterUseRequest({
    required this.tag,
    required this.mode,
    required this.sequence,
  });

  final String tag;
  final String mode;
  final int sequence;
}
