// 루트 프로젝트 — 플러그인 버전만 선언(apply false). 실제 적용은 :app 모듈에서.
plugins {
    id("com.android.application") version "8.1.4" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
}
