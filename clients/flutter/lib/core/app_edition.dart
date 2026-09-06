enum AppEdition { unified, admin, service }

extension AppEditionDetails on AppEdition {
  bool get isUnified => this == AppEdition.unified;
  bool get isAdmin => this == AppEdition.admin;
  bool get isService => this == AppEdition.service;

  String get title => switch (this) {
        AppEdition.unified => 'AstrAutoAnima Hub',
        AppEdition.admin => 'AstrAutoAnima 管理端',
        AppEdition.service => 'AstrAutoAnima',
      };
}
