// 루트 프로젝트 — 플러그인 버전만 선언(apply false). 실제 적용은 :app 모듈에서.
plugins {
    id("com.android.application") version "9.3.0" apply false
    id("org.jetbrains.kotlin.android") version "2.2.10" apply false
    id("com.google.firebase.appdistribution") version "5.1.1" apply false
}
